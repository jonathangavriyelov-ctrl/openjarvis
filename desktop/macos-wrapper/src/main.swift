import AppKit
import WebKit
import AVFoundation

let dashboardURL = URL(string: "http://localhost:5173/os/world")!
let backendHealth = URL(string: "http://127.0.0.1:8000/health")!
let frontendRoot = URL(string: "http://localhost:5173/")!
let localHosts: Set<String> = ["localhost", "127.0.0.1", "::1", "[::1]"]

func isLocal(_ url: URL?) -> Bool {
    guard let url = url else { return true }
    if url.scheme == "about" || url.scheme == "blob" || url.scheme == "data" { return true }
    return localHosts.contains(url.host ?? "")
}

final class LoadingView: NSView {
    let spinner = NSProgressIndicator()
    let title = NSTextField(labelWithString: "Jarvis")
    let status = NSTextField(wrappingLabelWithString: "Starting Jarvis…")
    let retry = NSButton(title: "Retry", target: nil, action: nil)
    let diagnostics = NSScrollView()
    let diagText = NSTextView()

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.backgroundColor = NSColor(calibratedRed: 0.04, green: 0.05, blue: 0.09, alpha: 1).cgColor
        title.font = .systemFont(ofSize: 42, weight: .thin)
        title.textColor = NSColor(calibratedRed: 0.55, green: 0.85, blue: 1, alpha: 1)
        status.font = .systemFont(ofSize: 14)
        status.textColor = NSColor(white: 0.8, alpha: 1)
        status.alignment = .center
        status.isSelectable = true
        spinner.style = .spinning
        spinner.controlSize = .regular
        spinner.appearance = NSAppearance(named: .darkAqua)
        spinner.startAnimation(nil)
        retry.isHidden = true
        retry.bezelStyle = .rounded

        // Diagnostics scroll view (hidden until an error occurs)
        diagText.isEditable = false
        diagText.isSelectable = true
        diagText.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        diagText.textColor = NSColor(calibratedRed: 0.7, green: 0.75, blue: 0.8, alpha: 1)
        diagText.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.07, blue: 0.11, alpha: 1)
        diagnostics.documentView = diagText
        diagnostics.hasVerticalScroller = true
        diagnostics.hasHorizontalScroller = true
        diagnostics.isHidden = true
        diagnostics.borderType = .bezelBorder

        let stack = NSStackView(views: [title, spinner, status, retry, diagnostics])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            status.widthAnchor.constraint(lessThanOrEqualToConstant: 560),
            diagnostics.widthAnchor.constraint(equalToConstant: 600),
            diagnostics.heightAnchor.constraint(equalToConstant: 200),
        ])
    }
    required init?(coder: NSCoder) { fatalError() }

    func showError(_ msg: String) {
        spinner.stopAnimation(nil); spinner.isHidden = true
        status.stringValue = msg
        status.textColor = NSColor(calibratedRed: 1, green: 0.6, blue: 0.55, alpha: 1)
        retry.isHidden = false
        // Load diagnostics from log files
        var diag = ""
        if let launcher = try? String(contentsOfFile: "/tmp/jarvis-launcher.log", encoding: .utf8) {
            diag += "=== Launcher Log ===\n" + launcher + "\n\n"
        }
        if let backend = try? String(contentsOfFile: "/tmp/jarvis-backend.log", encoding: .utf8) {
            let lines = backend.split(separator: "\n")
            let tail = lines.suffix(30)
            diag += "=== Backend Log (last 30 lines) ===\n" + tail.joined(separator: "\n") + "\n\n"
        }
        if let frontend = try? String(contentsOfFile: "/tmp/jarvis-frontend.log", encoding: .utf8) {
            let lines = frontend.split(separator: "\n")
            let tail = lines.suffix(30)
            diag += "=== Frontend Log (last 30 lines) ===\n" + tail.joined(separator: "\n")
        }
        diagText.string = diag.isEmpty ? "No logs found. Check /tmp/jarvis-*.log" : diag
        diagnostics.isHidden = false
    }
    func showProgress(_ msg: String) {
        spinner.isHidden = false; spinner.startAnimation(nil)
        status.stringValue = msg
        status.textColor = NSColor(white: 0.8, alpha: 1)
        retry.isHidden = true
        diagnostics.isHidden = true
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var loading: LoadingView!
    var pollTimer: Timer?
    var started = Date()
    var didLoad = false

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()   // persistent cookies/localStorage
        config.preferences.javaScriptCanOpenWindowsAutomatically = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.allowsMagnification = true
        webView.setValue(false, forKey: "drawsBackground")  // no white flash; window bg shows through
        webView.autoresizingMask = [.width, .height]

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Jarvis"
        window.minSize = NSSize(width: 700, height: 480)
        window.backgroundColor = NSColor(calibratedRed: 0.04, green: 0.05, blue: 0.09, alpha: 1)
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.center()
        window.setFrameAutosaveName("JarvisMainWindow")
        loading = LoadingView(frame: window.contentView!.bounds)
        loading.autoresizingMask = [.width, .height]
        loading.retry.target = self
        loading.retry.action = #selector(retryStart)
        window.contentView = loading
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startServersAndWait()
        // Diagnostics: distributed notification writes a snapshot to /tmp (used by build/test).
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(snapshot(_:)),
            name: Notification.Name("com.jonathan.jarvis.snapshot"), object: nil)
    }

    @objc func snapshot(_ n: Notification) {
        let url = webView.url?.absoluteString ?? "(none)"
        let state = window.contentView === webView ? "webview" : "loading"
        try? "state=\(state) url=\(url) frame=\(NSStringFromRect(window.frame))\n"
            .write(toFile: "/tmp/jarvis-app-state.txt", atomically: true, encoding: .utf8)
        guard let view = window.contentView else { return }
        let finish: (NSImage?) -> Void = { img in
            guard let img = img, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:]) else { return }
            try? png.write(to: URL(fileURLWithPath: "/tmp/jarvis-app-snapshot.png"))
        }
        if view === webView {
            webView.takeSnapshot(with: nil) { img, _ in finish(img) }
        } else if let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
            view.cacheDisplay(in: view.bounds, to: rep)
            let img = NSImage(size: view.bounds.size); img.addRepresentation(rep); finish(img)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }

    // MARK: servers
    @objc func retryStart() { startServersAndWait() }

    func startServersAndWait() {
        loading.showProgress("Checking Jarvis servers…")
        started = Date()
        if let script = Bundle.main.path(forResource: "start-servers", ofType: "sh") {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/bash")
            p.arguments = [script]
            // Capture output for diagnostics instead of discarding it
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            try? p.run()
            // Read launcher output asynchronously
            pipe.fileHandleForReading.readabilityHandler = { handle in
                if let line = String(data: handle.availableData, encoding: .utf8), !line.isEmpty {
                    DispatchQueue.main.async {
                        self.loading.showProgress(line.trimmingCharacters(in: .whitespacesAndNewlines))
                    }
                }
            }
        }
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.poll() }
        poll()
    }

    func check(_ url: URL, _ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 2.5)
        req.httpMethod = "GET"
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            done(code >= 200 && code < 500)
        }.resume()
    }

    var polling = false
    func poll() {
        if polling { return }
        polling = true
        let group = DispatchGroup()
        var b = false, f = false
        group.enter(); check(backendHealth) { b = $0; group.leave() }
        group.enter(); check(frontendRoot) { f = $0; group.leave() }
        group.notify(queue: .main) { [self] in
            polling = false
            let elapsed = Int(Date().timeIntervalSince(started))
            if b && f {
                pollTimer?.invalidate(); pollTimer = nil
                showDashboard()
            } else if elapsed >= 90 {
                pollTimer?.invalidate(); pollTimer = nil
                var parts: [String] = []
                if !b { parts.append("Backend (port 8000) did not respond — see /tmp/jarvis-backend.log") }
                if !f { parts.append("Frontend (port 5173) did not respond — see /tmp/jarvis-frontend.log") }
                loading.showError("Jarvis could not start after 90 seconds.\n\n" + parts.joined(separator: "\n"))
            } else {
                loading.showProgress("Starting Jarvis… (\(elapsed)s)\nBackend: \(b ? "ready" : "starting")   ·   Dashboard: \(f ? "ready" : "starting")")
            }
        }
    }

    func showDashboard() {
        if window.contentView !== webView {
            webView.frame = window.contentView!.bounds
            window.contentView = webView
        }
        if !didLoad { didLoad = true; webView.load(URLRequest(url: dashboardURL)) }
    }

    // MARK: menu actions
    @objc func reload(_ s: Any?) {
        if window.contentView === webView { webView.reload() } else { startServersAndWait() }
    }
    @objc func goBack(_ s: Any?) { webView.goBack() }
    @objc func goForward(_ s: Any?) { webView.goForward() }
    @objc func goHome(_ s: Any?) { webView.load(URLRequest(url: dashboardURL)) }
    @objc func zoomIn(_ s: Any?) { webView.pageZoom = min(webView.pageZoom + 0.1, 3) }
    @objc func zoomOut(_ s: Any?) { webView.pageZoom = max(webView.pageZoom - 0.1, 0.3) }
    @objc func zoomReset(_ s: Any?) { webView.pageZoom = 1 }
    @objc func openPage(_ s: NSMenuItem) {
        if let path = s.representedObject as? String, let u = URL(string: "http://localhost:5173" + path) {
            showDashboard(); webView.load(URLRequest(url: u))
        }
    }
    @objc func openDiagnostics(_ s: Any?) {
        let panel = NSOpenPanel()
        panel.message = "Jarvis log files are in /tmp"
        panel.directoryURL = URL(fileURLWithPath: "/tmp")
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = true
        panel.beginSheetModal(for: window) { _ in }
    }

    func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let top = NSMenuItem(); let m = NSMenu(title: title)
            items.forEach { m.addItem($0) }
            top.submenu = m; main.addItem(top); return m
        }
        func item(_ t: String, _ a: Selector?, _ k: String, _ mods: NSEvent.ModifierFlags = [.command]) -> NSMenuItem {
            let i = NSMenuItem(title: t, action: a, keyEquivalent: k); i.keyEquivalentModifierMask = mods; return i
        }
        let hideOthers = item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option])
        _ = add("Jarvis", [
            item("About Jarvis", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
            .separator(),
            item("Open Log Files", #selector(openDiagnostics(_:)), "L", [.command, .shift]),
            .separator(),
            item("Hide Jarvis", #selector(NSApplication.hide(_:)), "h"),
            hideOthers,
            item("Show All", #selector(NSApplication.unhideAllApplications(_:)), ""),
            .separator(),
            item("Quit Jarvis", #selector(NSApplication.terminate(_:)), "q"),
        ])
        _ = add("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Paste and Match Style", #selector(NSTextView.pasteAsPlainText(_:)), "v", [.command, .option, .shift]),
            item("Delete", #selector(NSText.delete(_:)), ""),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        _ = add("View", [
            item("Reload", #selector(reload(_:)), "r"),
            .separator(),
            item("Actual Size", #selector(zoomReset(_:)), "0"),
            item("Zoom In", #selector(zoomIn(_:)), "+"),
            item("Zoom Out", #selector(zoomOut(_:)), "-"),
            .separator(),
            item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ])
        var goItems = [
            item("Back", #selector(goBack(_:)), "["),
            item("Forward", #selector(goForward(_:)), "]"),
            item("Home (Worlds)", #selector(goHome(_:)), "H", [.command, .shift]),
            .separator(),
        ]
        for (i, (t, p)) in [("Worlds", "/os/world"), ("Chief", "/os/chief"), ("Goals", "/os/goals"),
                           ("Brain", "/os/brain"), ("Library", "/os/library")].enumerated() {
            let mi = item(t, #selector(openPage(_:)), "\(i + 1)")
            mi.representedObject = p; goItems.append(mi)
        }
        _ = add("Go", goItems)
        let win = add("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:)), ""),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.mainMenu = main
        NSApp.windowsMenu = win
    }

    // MARK: navigation — keep localhost in-app, send everything else to the default browser
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = action.request.url
        let mainFrame = action.targetFrame?.isMainFrame ?? true
        if let url = url, !isLocal(url), mainFrame,
           ["http", "https", "mailto", "tel"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if isLocal(url) { webView.load(action.request) } else { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation nav: WKNavigation!, withError error: Error) {
        let e = error as NSError
        if e.code == NSURLErrorCancelled { return }
        // Server may have gone away — go back to the loading screen and restart it.
        didLoad = false
        window.contentView = loading
        startServersAndWait()
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

    // Microphone / camera for hands-free voice (localhost only)
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(localHosts.contains(origin.host) ? .grant : .deny)
    }

    // JS panels (alert/confirm/prompt) and file pickers
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = "Jarvis"; a.informativeText = message
        a.addButton(withTitle: "OK"); a.runModal(); completionHandler()
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = "Jarvis"; a.informativeText = message
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert(); a.messageText = "Jarvis"; a.informativeText = prompt
        let tf = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        tf.stringValue = defaultText ?? ""; a.accessoryView = tf
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        completionHandler(a.runModal() == .alertFirstButtonReturn ? tf.stringValue : nil)
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = parameters.allowsMultipleSelection
        p.canChooseDirectories = parameters.allowsDirectories
        p.canChooseFiles = true
        p.beginSheetModal(for: window) { r in completionHandler(r == .OK ? p.urls : nil) }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
