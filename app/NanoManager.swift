// NanoManager — a small Mac app that runs the Nanoleaf control panel as a window.
//
// On launch it starts nanoleaf_server.py (unless one is already answering on the port),
// waits for it, then shows http://127.0.0.1:8765 in a web view. Quitting the app stops
// the server it started. Build + install with app/build_app.sh.
import Cocoa
import WebKit
import ScreenCaptureKit
import CoreMedia

let UI_PORT = 8765
let PAGE_URL = URL(string: "http://127.0.0.1:\(UI_PORT)/")!
// The app carries its own copy of the server (build_app.sh copies it in), and keeps
// its data in Application Support. Nothing touches Desktop/Documents, so macOS never
// has to ask for folder permission (a blocked prompt froze the first version).
let SERVER_DIR = (Bundle.main.resourcePath ?? "") + "/nanoleaf"
let DATA_DIR = NSHomeDirectory() + "/Library/Application Support/NanoManager"
let LOG_PATH = NSHomeDirectory() + "/Library/Logs/NanoManager.log"

func log(_ msg: String) {
    let df = DateFormatter(); df.dateFormat = "yyyy-MM-dd HH:mm:ss"
    let line = "\(df.string(from: Date())) \(msg)\n"
    if let h = FileHandle(forWritingAtPath: LOG_PATH) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile()
    } else {
        try? line.write(toFile: LOG_PATH, atomically: true, encoding: .utf8)
    }
}

// MARK: Replicate — share a tiny thumbnail of the main screen with the server
//
// While the server's Replicate effect is on, a ScreenCaptureKit stream captures the
// main display scaled down on the GPU to ~32x20 pixels, at most once a second.
// ScreenCaptureKit only delivers a frame when something on screen changed, and
// frames that barely differ from the last one sent are skipped, so a still screen
// costs next to nothing. NanoManager's own window is left out of the capture. When
// Replicate is off the stream is stopped; all that runs is a 2 s localhost check.
final class ScreenMood: NSObject, SCStreamOutput, SCStreamDelegate {
    let api = "http://127.0.0.1:\(UI_PORT)/api/replicate"
    let queue = DispatchQueue(label: "nanomanager.screenmood")
    var stream: SCStream?
    var starting = false
    var asked = false                       // the system permission prompt is shown once per launch
    var gridW = 32, gridH = 20
    var lastSent = [UInt8]()                // queue-only
    var posting = false, pending: Data?     // queue-only: one POST at a time, newest frame wins
    var timer: Timer?

    func begin() {
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.check() }
        check()
    }

    func end() { timer?.invalidate(); stop() }

    private func check() {
        var req = URLRequest(url: URL(string: api)!)
        req.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: req) { data, _, _ in
            let j = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let on = (j?["active"] as? Bool) ?? false
            if on, (j?["capturing"] as? Bool) == false {
                self.queue.async { self.lastSent = [] }     // server has no frame yet: send the next one even if unchanged
            }
            DispatchQueue.main.async { on ? self.start(width: j?["w"] as? Int ?? 32) : self.stop() }
        }.resume()
    }

    private var lastReported = ""
    private func report(_ error: String) {      // called from capture threads too, so hop to main
        guard Thread.isMainThread else { DispatchQueue.main.async { self.report(error) }; return }
        if error != lastReported { lastReported = error; log("replicate: \(error)") }
        var req = URLRequest(url: URL(string: api + "/status")!)
        req.httpMethod = "PUT"
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["error": error])
        URLSession.shared.dataTask(with: req).resume()
    }

    private func start(width: Int) {
        guard stream == nil, !starting else { return }
        starting = true
        // Just try: CGPreflightScreenCaptureAccess can keep answering "no" for a while
        // after the switch is turned on, so it's only used to explain a failure.
        SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: true) { content, error in
            DispatchQueue.main.async {
                defer { self.starting = false }
                guard let content = content else {
                    if !CGPreflightScreenCaptureAccess() {
                        if !self.asked { self.asked = true; _ = CGRequestScreenCaptureAccess() }
                        self.report("NanoManager needs Screen Recording permission: System Settings › Privacy & Security › Screen & System Audio Recording, turn NanoManager on, then reopen the app.")
                    } else {
                        self.report("Couldn't read the screen: \(error?.localizedDescription ?? "unknown error")")
                    }
                    return
                }
                let mainID = CGMainDisplayID()
                guard let display = content.displays.first(where: { $0.displayID == mainID }) ?? content.displays.first else {
                    self.report("No display to capture"); return
                }
                let me = content.applications.filter { $0.processID == ProcessInfo.processInfo.processIdentifier }
                let filter = SCContentFilter(display: display, excludingApplications: me, exceptingWindows: [])
                let w = max(8, min(64, width))
                let h = max(4, min(64, Int((Double(w) * Double(display.height) / Double(max(1, display.width))).rounded())))
                let cfg = SCStreamConfiguration()
                cfg.width = w
                cfg.height = h
                cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)     // ≤ 1 frame a second
                cfg.queueDepth = 3
                cfg.pixelFormat = kCVPixelFormatType_32BGRA
                cfg.colorSpaceName = CGColorSpace.sRGB
                cfg.showsCursor = false
                let s = SCStream(filter: filter, configuration: cfg, delegate: self)
                do { try s.addStreamOutput(self, type: .screen, sampleHandlerQueue: self.queue) }
                catch { self.report("Couldn't start capture: \(error.localizedDescription)"); return }
                self.gridW = w; self.gridH = h
                self.queue.async { self.lastSent = [] }
                self.stream = s
                s.startCapture { err in
                    guard let err = err else {
                        log("replicate: capturing \(w)x\(h)")
                        DispatchQueue.main.async { self.lastReported = "" }
                        return
                    }
                    DispatchQueue.main.async { if self.stream === s { self.stream = nil } }
                    self.report("Screen capture failed: \(err.localizedDescription)")
                }
            }
        }
    }

    private func stop() {
        guard let s = stream else { return }
        stream = nil
        s.stopCapture { _ in log("replicate: stopped") }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        DispatchQueue.main.async { if self.stream === stream { self.stream = nil } }
        report("Screen capture stopped: \(error.localizedDescription)")
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sb.isValid,
              let info = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let raw = info.first?[.status] as? Int, SCFrameStatus(rawValue: raw) == .complete,
              let pb = CMSampleBufferGetImageBuffer(sb) else { return }
        CVPixelBufferLockBaseAddress(pb, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(pb)?.assumingMemoryBound(to: UInt8.self) else { return }
        let w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb), row = CVPixelBufferGetBytesPerRow(pb)
        var rgb = [UInt8](repeating: 0, count: w * h * 3)
        for y in 0..<h {
            for x in 0..<w {
                let i = y * row + x * 4, o = (y * w + x) * 3
                rgb[o] = base[i + 2]; rgb[o + 1] = base[i + 1]; rgb[o + 2] = base[i]     // BGRA -> RGB
            }
        }
        if rgb.count == lastSent.count {        // skip frames that barely changed (cursor blink, clock tick)
            var total = 0
            for i in 0..<rgb.count { total += abs(Int(rgb[i]) - Int(lastSent[i])) }
            if total < rgb.count * 2 { return }
        }
        lastSent = rgb
        let hex = Array("0123456789abcdef".utf8)
        var px = [UInt8](repeating: 0, count: rgb.count * 2)
        for (i, b) in rgb.enumerated() { px[i * 2] = hex[Int(b >> 4)]; px[i * 2 + 1] = hex[Int(b & 15)] }
        let body = try? JSONSerialization.data(withJSONObject: ["w": w, "h": h, "px": String(decoding: px, as: UTF8.self)])
        pending = body
        send()
    }

    private func send() {                       // on queue
        guard !posting, let body = pending else { return }
        pending = nil; posting = true
        var req = URLRequest(url: URL(string: api + "/frame")!)
        req.httpMethod = "PUT"
        req.timeoutInterval = 3
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        URLSession.shared.dataTask(with: req) { data, _, _ in
            let j = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            if let on = j?["active"] as? Bool, !on { DispatchQueue.main.async { self.stop() } }
            self.queue.async { self.posting = false; self.send() }
        }.resume()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    // The phone's Home Screen app goes through this Mac, so don't let it idle-sleep while open.
    var awake: NSObjectProtocol?
    let mood = ScreenMood()

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        awake = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled],
                                                      reason: "NanoManager serves the panels to phones on the Wi-Fi")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "NanoManager"
        window.minSize = NSSize(width: 720, height: 520)
        window.backgroundColor = NSColor(red: 0.05, green: 0.06, blue: 0.09, alpha: 1)
        window.isReleasedWhenClosed = false
        if !window.setFrameUsingName("NanoManagerMain") { window.center() }
        window.setFrameAutosaveName("NanoManagerMain")

        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: window.contentView!.bounds, configuration: cfg)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window.contentView!.addSubview(web)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        log("launched; server dir \(SERVER_DIR); data dir \(DATA_DIR)")
        showStatus("Starting the panels server…")
        startServerIfNeeded()
        mood.begin()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ note: Notification) {
        mood.end()
        if let p = server, p.isRunning { log("quitting; stopping server"); p.terminate() }
    }

    // MARK: server
    func startServerIfNeeded() {
        ping { alive in
            if alive { log("server already answering; loading page"); self.load(); return }
            let fm = FileManager.default
            guard fm.fileExists(atPath: SERVER_DIR + "/nanoleaf_server.py") else {
                log("nanoleaf_server.py missing from \(SERVER_DIR)")
                self.showStatus("This copy of NanoManager has no server inside it.<br><small>Rebuild it with app/build_app.sh in the nanoleaf folder.</small>")
                return
            }
            try? fm.createDirectory(atPath: DATA_DIR, withIntermediateDirectories: true)
            // first run: seed the data folder with the pairing token and saved scenes built in
            for f in ["token.txt", "scenes.json", "ui_state.json", "palettes.json"] {
                if !fm.fileExists(atPath: DATA_DIR + "/" + f), fm.fileExists(atPath: SERVER_DIR + "/" + f) {
                    try? fm.copyItem(atPath: SERVER_DIR + "/" + f, toPath: DATA_DIR + "/" + f)
                }
            }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = ["-u", "nanoleaf_server.py"]
            p.currentDirectoryURL = URL(fileURLWithPath: SERVER_DIR)
            var env = ProcessInfo.processInfo.environment
            env["NANOLEAF_UI_PORT"] = String(UI_PORT)
            env["NANOLEAF_DATA_DIR"] = DATA_DIR
            env["NANOLEAF_LISTEN"] = "0.0.0.0"      // so the iPhone Home Screen app can reach it over Wi-Fi
            p.environment = env
            let logPath = DATA_DIR + "/server.log"
            if !FileManager.default.fileExists(atPath: logPath) {
                FileManager.default.createFile(atPath: logPath, contents: nil)
            }
            if let log = FileHandle(forWritingAtPath: logPath) {
                log.seekToEndOfFile()
                p.standardOutput = log
                p.standardError = log
            } else {
                p.standardOutput = FileHandle.nullDevice
                p.standardError = FileHandle.nullDevice
            }
            p.terminationHandler = { proc in
                DispatchQueue.main.async {
                    guard self.server === proc else { return }
                    self.server = nil
                    log("server exited with status \(proc.terminationStatus)")
                    self.showStatus("The panels server stopped (exit \(proc.terminationStatus)).<br><small>See server.log in the NanoManager data folder (View menu), then press ⌘R.</small>")
                }
            }
            do { try p.run(); self.server = p; log("server started, pid \(p.processIdentifier)") }
            catch {
                log("could not start server: \(error)")
                self.showStatus("Could not start the server: \(error.localizedDescription)")
                return
            }
            self.waitForServer(tries: 60)
        }
    }

    func waitForServer(tries: Int) {
        ping { alive in
            if alive { log("server answering; loading page"); self.load() }
            else if tries > 0 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitForServer(tries: tries - 1) }
            } else {
                log("server never answered on port \(UI_PORT)")
                self.showStatus("The server didn't answer on port \(UI_PORT).<br><small>Check server.log in the NanoManager data folder (View menu), then press ⌘R.</small>")
            }
        }
    }

    func ping(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: PAGE_URL)
        req.timeoutInterval = 1.5
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    // MARK: page
    func load() { web.load(URLRequest(url: PAGE_URL)) }

    func showStatus(_ msg: String) {
        let html = """
        <!doctype html><meta charset="utf-8"><body style="margin:0;background:#0d1017;color:#e6e9f0;
        font:15px -apple-system,system-ui;display:grid;place-items:center;height:100vh;text-align:center">
        <div><div style="font-size:44px;margin-bottom:14px">◆</div>\(msg)</div></body>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    @objc func reload(_ s: Any?) {
        if web.url == nil || web.url?.scheme != "http" { startServerIfNeeded() } else { web.reload() }
    }
    @objc func openInBrowser(_ s: Any?) { NSWorkspace.shared.open(PAGE_URL) }
    @objc func revealFolder(_ s: Any?) {
        NSWorkspace.shared.selectFile(DATA_DIR + "/server.log", inFileViewerRootedAtPath: DATA_DIR)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showStatus("Lost the panels server.<br><small>\(error.localizedDescription) — press ⌘R to retry.</small>")
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        showStatus("Can't reach the panels server.<br><small>\(error.localizedDescription) — press ⌘R to retry.</small>")
    }
    // Links that try to open a new window go to the normal browser instead.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = navigationAction.request.url { NSWorkspace.shared.open(u) }
        return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.runModal(); completionHandler()
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    // MARK: menu (needed for ⌘Q, ⌘C/⌘V in text fields, ⌘R)
    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About NanoManager", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide NanoManager", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = appMenu.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit NanoManager", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload(_:)), keyEquivalent: "r")
        let ob = view.addItem(withTitle: "Open in Browser", action: #selector(openInBrowser(_:)), keyEquivalent: "o")
        ob.keyEquivalentModifierMask = [.command, .shift]
        view.addItem(withTitle: "Show Data Folder in Finder", action: #selector(revealFolder(_:)), keyEquivalent: "")
        view.addItem(.separator())
        let fs = view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fs.keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = view

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        winItem.submenu = win
        NSApp.windowsMenu = win

        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
