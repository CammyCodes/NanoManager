package io.github.cammycodes.nanomanager.tv;

import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/**
 * Talks to the Nanoleaf controller. Same hard rules as nanoleaf_server.py:
 * one write in flight, at least MIN_GAP ms between writes, latest-wins per key,
 * and a breaker that pauses writes for PAUSE ms after 3 network failures in a row
 * (HTTP error codes don't count). The controller crashed once when it was flooded.
 */
public class Device {
    public interface Listener {
        void onWrite(String key, int status, String body);
        void onRead(String id, int status, String body);
        void onStatus(JSONObject status);
    }

    static final long MIN_GAP = 650;
    static final long PAUSE = 20000;
    static final int BREAKER = 3;
    static final long PAIR_WINDOW = 90000;

    private static class Job {
        final String method, path, body;
        Job(String m, String p, String b) { method = m; path = p; body = b; }
    }

    private final Listener listener;
    private final SharedPreferences prefs;
    private volatile String ip, token;
    private volatile int port;

    private final Object lock = new Object();
    private final LinkedHashMap<String, Job> queue = new LinkedHashMap<>();
    private long lastWrite = 0, pausedUntil = 0;
    private int netFails = 0;
    private final ExecutorService readers = Executors.newFixedThreadPool(2);
    private final ExecutorService jobs = Executors.newSingleThreadExecutor();
    private volatile boolean reconnecting = false;

    public Device(Listener l, SharedPreferences p, JSONObject seed) {
        listener = l;
        prefs = p;
        ip = p.getString("ip", seed.optString("ip", ""));
        port = p.getInt("port", seed.optInt("port", 16021));
        token = p.getString("token", seed.optString("token", ""));
        Thread t = new Thread(this::writeLoop, "nanoleaf-writer");
        t.setDaemon(true);
        t.start();
    }

    public String ip() { return ip; }

    public boolean paused() {
        synchronized (lock) { return System.currentTimeMillis() < pausedUntil; }
    }

    // ---------------------------------------------------------------- writes
    public void write(String key, String method, String path, String body) {
        synchronized (lock) {
            queue.remove(key);                 // re-insert so a fresh value goes to the back
            queue.put(key, new Job(method, path, body));
            lock.notifyAll();
        }
    }

    private void writeLoop() {
        while (true) {
            String key;
            Job job;
            boolean rejected = false;
            try {
                synchronized (lock) {
                    while (queue.isEmpty()) lock.wait();
                    long now = System.currentTimeMillis();
                    long wait = lastWrite + MIN_GAP - now;
                    if (wait > 0 && now >= pausedUntil) { lock.wait(wait); continue; }
                    Iterator<Map.Entry<String, Job>> it = queue.entrySet().iterator();
                    Map.Entry<String, Job> e = it.next();
                    it.remove();
                    key = e.getKey();
                    job = e.getValue();
                    if (now < pausedUntil) rejected = true;
                }
            } catch (InterruptedException ie) {
                return;
            }
            if (rejected) {
                listener.onWrite(key, 503, "{\"error\":\"paused\"}");
                continue;
            }
            int[] st = new int[1];
            String res = http(job.method, base() + job.path, job.body, 4000, st);
            synchronized (lock) {
                lastWrite = System.currentTimeMillis();
                if (st[0] == 0) {
                    if (++netFails >= BREAKER) { pausedUntil = lastWrite + PAUSE; netFails = 0; }
                } else {
                    netFails = 0;
                }
            }
            listener.onWrite(key, st[0], res);
            if (st[0] == 0 && !reconnecting) autoReconnect();
        }
    }

    // ---------------------------------------------------------------- reads
    public void read(final String id, final String path) {
        readers.execute(() -> {
            int[] st = new int[1];
            String res = http("GET", base() + path, null, 4000, st);
            listener.onRead(id, st[0], res);
        });
    }

    private String tok() { return token.isEmpty() ? "unpaired" : token; }

    private String base() { return "http://" + ip + ":" + port + "/api/v1/" + tok(); }

    static String http(String method, String url, String body, int timeout, int[] status) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod(method);
            c.setConnectTimeout(Math.min(timeout, 2500));
            c.setReadTimeout(timeout);
            c.setUseCaches(false);
            if (body != null) {
                byte[] b = body.getBytes("UTF-8");
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.setFixedLengthStreamingMode(b.length);
                OutputStream o = c.getOutputStream();
                o.write(b);
                o.close();
            }
            status[0] = c.getResponseCode();
            InputStream in = status[0] >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in == null) return "";
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            in.close();
            return out.toString("UTF-8");
        } catch (Exception e) {
            status[0] = 0;
            return "{\"error\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}";
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ---------------------------------------------------------------- reconnect / pair
    private long lastAuto = 0;

    /** While offline, look for the panels at most once a minute. Never pairs by itself. */
    public void autoReconnect() {
        long now = System.currentTimeMillis();
        if (reconnecting || now - lastAuto < 60000) return;
        lastAuto = now;
        reconnect(false);
    }

    public void reconnect(final boolean pair) {
        if (reconnecting) return;
        reconnecting = true;
        jobs.execute(() -> {
            try { reconnectJob(pair); } finally { reconnecting = false; }
        });
    }

    private void status(String phase, String detail) {
        try {
            JSONObject o = new JSONObject();
            o.put("phase", phase);
            o.put("detail", detail);
            o.put("ip", ip);
            listener.onStatus(o);
        } catch (Exception ignored) { }
    }

    /** 200 = ours, 401/403 = a Nanoleaf that doesn't know our token, 0 = nothing there. */
    private int probe(String host) {
        int[] st = new int[1];
        http("GET", "http://" + host + ":" + port + "/api/v1/" + tok() + "/", null, 2500, st);
        return st[0];
    }

    private void reconnectJob(boolean pair) {
        status("checking", "Checking " + ip);
        int s = probe(ip);
        String found = s == 200 ? ip : null, locked = (s == 401 || s == 403) ? ip : null;
        if (found == null && locked == null) {
            status("searching", "Searching the network for the panels");
            for (String host : scan()) {
                int r = probe(host);
                if (r == 200) { found = host; break; }
                if ((r == 401 || r == 403) && locked == null) locked = host;
            }
        }
        if (found != null) {
            save(found, token);
            status("connected", "Connected to " + found);
            return;
        }
        if (locked == null) {
            status("not_found", "Couldn't find the panels on the network");
            return;
        }
        ip = locked;
        if (!pair) {
            status("needs_pairing", "Found the panels at " + locked + " but they need pairing");
            return;
        }
        long end = System.currentTimeMillis() + PAIR_WINDOW;
        while (System.currentTimeMillis() < end) {
            status("pairing", "Hold the power button on the controller for 5-7 seconds until the lights flash");
            int[] st = new int[1];
            String res = http("POST", "http://" + locked + ":" + port + "/api/v1/new", "", 3000, st);
            if (st[0] == 200) {
                try {
                    String t = new JSONObject(res).getString("auth_token");
                    save(locked, t);
                    status("connected", "Paired with " + locked);
                    return;
                } catch (Exception ignored) { }
            }
            try { Thread.sleep(2000); } catch (InterruptedException e) { return; }
        }
        status("needs_pairing", "Pairing timed out. Try again and hold the button a little longer.");
    }

    private void save(String newIp, String newToken) {
        ip = newIp;
        token = newToken;
        prefs.edit().putString("ip", newIp).putString("token", newToken).putInt("port", port).apply();
    }

    /** Hosts on our /24 (and the last known IP's /24) with port 16021 open. */
    private List<String> scan() {
        List<String> prefixes = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address) {
                        String h = a.getHostAddress();
                        String p = h.substring(0, h.lastIndexOf('.') + 1);
                        if (!prefixes.contains(p)) prefixes.add(p);
                    }
                }
            }
        } catch (Exception ignored) { }
        if (ip.lastIndexOf('.') > 0) {
            String own = ip.substring(0, ip.lastIndexOf('.') + 1);
            if (!prefixes.contains(own)) prefixes.add(own);
        }

        ExecutorService pool = Executors.newFixedThreadPool(48);
        List<Future<String>> fs = new ArrayList<>();
        for (String p : prefixes) {
            for (int i = 1; i < 255; i++) {
                final String host = p + i;
                fs.add(pool.submit(() -> {
                    try (Socket so = new Socket()) {
                        so.connect(new InetSocketAddress(host, port), 400);
                        return host;
                    } catch (Exception e) {
                        return null;
                    }
                }));
            }
        }
        List<String> open = new ArrayList<>();
        for (Future<String> f : fs) {
            try {
                String h = f.get(5, TimeUnit.SECONDS);
                if (h != null) open.add(h);
            } catch (Exception ignored) { }
        }
        pool.shutdownNow();
        return open;
    }
}
