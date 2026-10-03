package io.github.cammycodes.nanomanager.tv;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/** Full-screen WebView running assets/tv.html, with a bridge ("NL") to Device. */
public class MainActivity extends Activity implements Device.Listener {
    private WebView web;
    private Device device;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        prefs = getSharedPreferences("nanoleaf", Context.MODE_PRIVATE);
        device = new Device(this, prefs, seedConfig());

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0b0d14"));
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        web.setWebViewClient(new WebViewClient());
        web.addJavascriptInterface(new Bridge(), "NL");
        web.loadUrl("file:///android_asset/tv.html");
        setContentView(web);
        web.requestFocus(View.FOCUS_DOWN);
    }

    private JSONObject seedConfig() {
        try {
            InputStream in = getAssets().open("config.json");
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            in.close();
            return new JSONObject(out.toString("UTF-8"));
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    // ------------------------------------------------------------ JS callbacks
    private void js(final String code) {
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript(code, null); });
    }

    @Override
    public void onWrite(String key, int status, String body) {
        js("TV.onWrite(" + JSONObject.quote(key) + "," + status + "," + JSONObject.quote(body) + ")");
    }

    @Override
    public void onRead(String id, int status, String body) {
        js("TV.onRead(" + JSONObject.quote(id) + "," + status + "," + JSONObject.quote(body) + ")");
    }

    @Override
    public void onStatus(JSONObject st) {
        js("TV.onStatus(" + st.toString() + ")");
    }

    // ------------------------------------------------------------ remote keys
    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        String k = null;
        switch (e.getKeyCode()) {
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
            case KeyEvent.KEYCODE_MEDIA_PLAY:
            case KeyEvent.KEYCODE_MEDIA_PAUSE: k = "power"; break;
            case KeyEvent.KEYCODE_MEDIA_REWIND: k = "dimmer"; break;
            case KeyEvent.KEYCODE_MEDIA_FAST_FORWARD: k = "brighter"; break;
            case KeyEvent.KEYCODE_MENU: k = "menu"; break;
        }
        if (k != null) {
            if (e.getAction() == KeyEvent.ACTION_DOWN) js("TV.remote(" + JSONObject.quote(k) + ")");
            return true;
        }
        return super.dispatchKeyEvent(e);
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("TV.back()", r -> { if (!"true".equals(r)) finish(); });
    }

    @Override
    protected void onResume() {
        super.onResume();
        js("window.TV&&TV.visible(true)");
    }

    @Override
    protected void onPause() {
        js("window.TV&&TV.visible(false)");
        super.onPause();
    }

    // ------------------------------------------------------------ bridge
    public class Bridge {
        @JavascriptInterface public void write(String key, String method, String path, String body) {
            device.write(key, method, path, body);
        }
        @JavascriptInterface public void read(String id, String path) { device.read(id, path); }
        @JavascriptInterface public void reconnect(boolean pair) { device.reconnect(pair); }
        @JavascriptInterface public String ip() { return device.ip(); }
        @JavascriptInterface public boolean paused() { return device.paused(); }
        @JavascriptInterface public String pref(String key) { return prefs.getString("ui." + key, null); }
        @JavascriptInterface public void setPref(String key, String value) {
            prefs.edit().putString("ui." + key, value).apply();
        }
        @JavascriptInterface public void exit() { runOnUiThread(MainActivity.this::finish); }
    }
}
