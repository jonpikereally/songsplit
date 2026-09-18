// SongSplit — native macOS front end for songsplit.py
// Build: swiftc -O main.swift -o SongSplit
import Cocoa
import UniformTypeIdentifiers

let PY = "/usr/bin/python3"
var SPLITTER = ""   // resolved at launch, relative to the .app

// MARK: - build info (stamped into Info.plist by scripts/build_app.sh)

enum BuildInfo {
    static let info = Bundle.main.infoDictionary ?? [:]
    static let version = info["CFBundleShortVersionString"] as? String ?? "0.0.0"
    static let build = info["CFBundleVersion"] as? String ?? "0"
    static let date = info["SongSplitBuildDate"] as? String ?? "unknown date"
    static let commit = info["SongSplitGitCommit"] as? String ?? "local"
    static var summary: String { "Version \(version) (build \(build)) · built \(date) · \(commit)" }
}

// MARK: - updates (GitHub releases)

struct UpdateError: LocalizedError {
    let msg: String
    init(_ m: String) { msg = m }
    var errorDescription: String? { msg }
}

struct Release {
    let version: String   // "1.2.0"
    let notes: String
    let zip: URL?         // first .zip asset, if any
    let page: URL         // release page on GitHub
}

enum Updater {
    static let repo = "jonpikereally/songsplit"
    static let releasesPage = URL(string: "https://github.com/\(repo)/releases")!

    static func fetchLatest(_ done: @escaping (Result<Release, Error>) -> Void) {
        var req = URLRequest(url: URL(string: "https://api.github.com/repos/\(repo)/releases/latest")!)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("SongSplit/\(BuildInfo.version)", forHTTPHeaderField: "User-Agent")
        req.timeoutInterval = 15
        URLSession.shared.dataTask(with: req) { data, resp, err in
            if let err = err { return done(.failure(err)) }
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            if code == 404 { return done(.failure(UpdateError("No releases have been published yet."))) }
            guard code == 200, let data = data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tag = obj["tag_name"] as? String else {
                return done(.failure(UpdateError("Unexpected reply from GitHub (HTTP \(code)).")))
            }
            let assets = obj["assets"] as? [[String: Any]] ?? []
            let zip = assets.first { ($0["name"] as? String)?.hasSuffix(".zip") == true }
                .flatMap { ($0["browser_download_url"] as? String).flatMap { URL(string: $0) } }
            let page = (obj["html_url"] as? String).flatMap { URL(string: $0) } ?? releasesPage
            done(.success(Release(version: tag, notes: obj["body"] as? String ?? "",
                                  zip: zip, page: page)))
        }.resume()
    }

    // "v1.2.10" -> [1, 2, 10]
    static func parts(_ s: String) -> [Int] {
        s.drop { !$0.isNumber }.split(separator: ".").map { Int($0.prefix { $0.isNumber }) ?? 0 }
    }
    static func isNewer(_ a: String, than b: String) -> Bool {
        var x = parts(a), y = parts(b)
        while x.count < y.count { x.append(0) }
        while y.count < x.count { y.append(0) }
        return x.lexicographicallyPrecedes(y) == false && x != y
    }

    /// Downloads the zip, unpacks it, and returns the new .app inside a temp folder.
    static func download(_ zip: URL, _ done: @escaping (Result<URL, Error>) -> Void) {
        URLSession.shared.downloadTask(with: zip) { tmp, _, err in
            if let err = err { return done(.failure(err)) }
            guard let tmp = tmp else { return done(.failure(UpdateError("Download produced no file."))) }
            do {
                let fm = FileManager.default
                let stage = fm.temporaryDirectory.appendingPathComponent("SongSplit-update-\(UUID().uuidString)")
                try fm.createDirectory(at: stage, withIntermediateDirectories: true)
                let zipFile = stage.appendingPathComponent("SongSplit.zip")
                try fm.moveItem(at: tmp, to: zipFile)
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
                p.arguments = ["-x", "-k", zipFile.path, stage.path]
                try p.run(); p.waitUntilExit()
                guard p.terminationStatus == 0 else { throw UpdateError("Could not unpack the update.") }
                let apps = try fm.contentsOfDirectory(at: stage, includingPropertiesForKeys: nil)
                    .filter { $0.pathExtension == "app" }
                guard let app = apps.first else { throw UpdateError("The update didn't contain an app.") }
                done(.success(app))
            } catch { done(.failure(error)) }
        }.resume()
    }

    /// Swaps the running bundle for `newApp`; the old one goes to the Trash.
    static func replaceRunningApp(with newApp: URL) throws {
        let fm = FileManager.default
        let current = Bundle.main.bundleURL
        let parent = current.deletingLastPathComponent()
        guard fm.isWritableFile(atPath: parent.path) else {
            throw UpdateError("The folder containing SongSplit (\(parent.path)) isn't writable.")
        }
        let old = parent.appendingPathComponent("SongSplit (old).app")
        try? fm.removeItem(at: old)
        try fm.moveItem(at: current, to: old)
        do { try fm.moveItem(at: newApp, to: current) } catch {
            try? fm.moveItem(at: old, to: current)   // put the original back
            throw error
        }
        if (try? fm.trashItem(at: old, resultingItemURL: nil)) == nil { try? fm.removeItem(at: old) }
    }

    /// Starts the (now replaced) app after this process exits.
    static func relaunch() {
        let path = Bundle.main.bundleURL.path
        let quoted = "'" + path.replacingOccurrences(of: "'", with: "'\\''") + "'"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", "sleep 1; /usr/bin/open -n \(quoted)"]
        try? p.run()
        NSApp.terminate(nil)
    }
}

// MARK: - drop target

final class DropView: NSView {
    var onDrop: (([URL]) -> Void)?
    private var lit = false

    override init(frame: NSRect) {
        super.init(frame: frame)
        registerForDraggedTypes([.fileURL])
        wantsLayer = true
        layer?.cornerRadius = 10
    }
    required init?(coder: NSCoder) { fatalError() }

    private func urls(_ sender: NSDraggingInfo) -> [URL] {
        (sender.draggingPasteboard.readObjects(forClasses: [NSURL.self],
            options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
    }
    override func draggingEntered(_ s: NSDraggingInfo) -> NSDragOperation {
        lit = !urls(s).isEmpty; needsDisplay = true
        return lit ? .copy : []
    }
    override func draggingExited(_ s: NSDraggingInfo?) { lit = false; needsDisplay = true }
    override func performDragOperation(_ s: NSDraggingInfo) -> Bool {
        lit = false; needsDisplay = true
        let u = urls(s)
        if u.isEmpty { return false }
        onDrop?(u)
        return true
    }
    override func draw(_ r: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 1, dy: 1),
                                xRadius: 10, yRadius: 10)
        (lit ? NSColor.controlAccentColor.withAlphaComponent(0.10)
             : NSColor.textBackgroundColor).setFill()
        path.fill()
        path.lineWidth = lit ? 2 : 1
        let dash: [CGFloat] = lit ? [] : [5, 4]
        path.setLineDash(dash, count: dash.count, phase: 0)
        (lit ? NSColor.controlAccentColor : NSColor.separatorColor).setStroke()
        path.stroke()
    }
}

// MARK: - app

final class Controller: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var drop: DropView!
    var fileLabel: NSTextField!
    var csvLabel: NSTextField!
    var status: NSTextField!
    var logView: NSTextView!
    var bar: NSProgressIndicator!
    var goButton: NSButton!
    var stopButton: NSButton!
    var revealButton: NSButton!
    var dryBox: NSButton!
    var offlineBox: NSButton!

    var audio: [URL] = []
    var csvs: [URL] = []
    var task: Process?
    var outDir: String?

    // ---------- layout
    func applicationDidFinishLaunching(_ n: Notification) {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 620),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable],
                         backing: .buffered, defer: false)
        w.title = "SongSplit"
        w.center()
        w.minSize = NSSize(width: 660, height: 520)
        window = w

        let root = NSView(frame: w.contentView!.bounds)
        root.autoresizingMask = [.width, .height]
        w.contentView = root

        let title = label("SongSplit", size: 22, weight: .bold)
        title.frame = NSRect(x: 24, y: 566, width: 400, height: 30)
        title.autoresizingMask = [.minYMargin]
        root.addSubview(title)

        let sub = label("Split one long recording into separate, tagged songs.",
                        size: 12, weight: .regular, secondary: true)
        sub.frame = NSRect(x: 24, y: 545, width: 400, height: 18)
        sub.autoresizingMask = [.minYMargin]
        root.addSubview(sub)

        let ver = label(BuildInfo.summary, size: 11, weight: .regular, secondary: true)
        ver.alignment = .right
        ver.frame = NSRect(x: 336, y: 572, width: 400, height: 18)
        ver.autoresizingMask = [.minXMargin, .minYMargin]
        root.addSubview(ver)

        let upd = button("Check for Updates…", #selector(checkForUpdatesClicked))
        upd.controlSize = .small
        upd.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        upd.frame = NSRect(x: 596, y: 543, width: 140, height: 22)
        upd.autoresizingMask = [.minXMargin, .minYMargin]
        root.addSubview(upd)

        drop = DropView(frame: NSRect(x: 24, y: 432, width: 712, height: 104))
        drop.autoresizingMask = [.width, .minYMargin]
        drop.onDrop = { [weak self] urls in self?.accept(urls) }
        root.addSubview(drop)

        fileLabel = label("", size: 13, weight: .medium)
        fileLabel.frame = NSRect(x: 16, y: 60, width: 680, height: 20)
        fileLabel.autoresizingMask = [.width]
        drop.addSubview(fileLabel)

        csvLabel = label("", size: 11, weight: .regular, secondary: true)
        csvLabel.frame = NSRect(x: 16, y: 40, width: 680, height: 18)
        csvLabel.autoresizingMask = [.width]
        drop.addSubview(csvLabel)

        let pick = button("Choose audio…", #selector(pickAudio))
        pick.frame = NSRect(x: 16, y: 10, width: 130, height: 24)
        drop.addSubview(pick)
        let pickCsv = button("Add playlist CSV…", #selector(pickCSV))
        pickCsv.frame = NSRect(x: 152, y: 10, width: 150, height: 24)
        drop.addSubview(pickCsv)
        let clear = button("Clear", #selector(clearFiles))
        clear.frame = NSRect(x: 308, y: 10, width: 70, height: 24)
        drop.addSubview(clear)

        dryBox = checkbox("Preview only — write nothing")
        dryBox.frame = NSRect(x: 24, y: 400, width: 240, height: 20)
        dryBox.autoresizingMask = [.minYMargin]
        root.addSubview(dryBox)

        offlineBox = checkbox("Skip song identification (offline)")
        offlineBox.frame = NSRect(x: 280, y: 400, width: 260, height: 20)
        offlineBox.autoresizingMask = [.minYMargin]
        root.addSubview(offlineBox)

        goButton = button("Split", #selector(start))
        goButton.frame = NSRect(x: 24, y: 362, width: 90, height: 28)
        goButton.keyEquivalent = "\r"
        goButton.bezelStyle = .rounded
        goButton.autoresizingMask = [.minYMargin]
        root.addSubview(goButton)

        stopButton = button("Stop", #selector(stop))
        stopButton.frame = NSRect(x: 122, y: 362, width: 70, height: 28)
        stopButton.isEnabled = false
        stopButton.autoresizingMask = [.minYMargin]
        root.addSubview(stopButton)

        revealButton = button("Show in Finder", #selector(reveal))
        revealButton.frame = NSRect(x: 200, y: 362, width: 130, height: 28)
        revealButton.isEnabled = false
        revealButton.autoresizingMask = [.minYMargin]
        root.addSubview(revealButton)

        status = label("Ready", size: 11, weight: .regular, secondary: true)
        status.alignment = .right
        status.frame = NSRect(x: 500, y: 368, width: 236, height: 18)
        status.autoresizingMask = [.minXMargin, .minYMargin]
        root.addSubview(status)

        bar = NSProgressIndicator(frame: NSRect(x: 24, y: 340, width: 712, height: 12))
        bar.isIndeterminate = true
        bar.style = .bar
        bar.autoresizingMask = [.width, .minYMargin]
        root.addSubview(bar)

        let scroll = NSScrollView(frame: NSRect(x: 24, y: 24, width: 712, height: 300))
        scroll.autoresizingMask = [.width, .height]
        scroll.hasVerticalScroller = true
        scroll.borderType = .lineBorder
        logView = NSTextView(frame: scroll.bounds)
        logView.isEditable = false
        logView.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        logView.textContainerInset = NSSize(width: 8, height: 8)
        logView.autoresizingMask = [.width]
        scroll.documentView = logView
        root.addSubview(scroll)

        refresh()
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // quiet check on launch; only speaks up if there's something newer
        if UserDefaults.standard.object(forKey: "SongSplitAutoUpdateCheck") as? Bool ?? true {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                self?.checkForUpdates(manual: false)
            }
        }
    }

    // ---------- about & updates
    @objc func about() {
        let credits = NSAttributedString(
            string: "Build \(BuildInfo.build) · \(BuildInfo.date)\nCommit \(BuildInfo.commit)",
            attributes: [.font: NSFont.systemFont(ofSize: 11),
                         .foregroundColor: NSColor.secondaryLabelColor])
        NSApp.orderFrontStandardAboutPanel(options: [.credits: credits])
    }

    @objc func checkForUpdatesClicked() { checkForUpdates(manual: true) }

    func checkForUpdates(manual: Bool) {
        if manual { setStatus("Checking for updates…", .secondaryLabelColor) }
        Updater.fetchLatest { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch result {
                case .failure(let e):
                    guard manual else { return }
                    self.setStatus("Ready", .secondaryLabelColor)
                    self.alert("Couldn't check for updates", e.localizedDescription)
                case .success(let r):
                    if Updater.isNewer(r.version, than: BuildInfo.version) {
                        self.offer(r)
                    } else if manual {
                        self.setStatus("Up to date", .systemGreen)
                        self.alert("You're up to date",
                                   "SongSplit \(BuildInfo.version) (build \(BuildInfo.build)) is the latest version.")
                    }
                }
            }
        }
    }

    func offer(_ r: Release) {
        if task != nil {
            alert("Update available", "SongSplit \(r.version) is available. Finish or stop the current split, then choose Check for Updates… to install it.")
            return
        }
        let a = NSAlert()
        a.messageText = "SongSplit \(Updater.parts(r.version).map(String.init).joined(separator: ".")) is available"
        var info = "You have \(BuildInfo.version) (build \(BuildInfo.build), \(BuildInfo.date))."
        let notes = r.notes.trimmingCharacters(in: .whitespacesAndNewlines)
        if !notes.isEmpty { info += "\n\n" + String(notes.prefix(600)) }
        a.informativeText = info
        a.addButton(withTitle: r.zip != nil ? "Download and Install" : "Open Download Page")
        a.addButton(withTitle: "Later")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        if let zip = r.zip { install(zip, page: r.page) }
        else { NSWorkspace.shared.open(r.page) }
    }

    func install(_ zip: URL, page: URL) {
        setStatus("Downloading update…", .labelColor)
        bar.startAnimation(nil)
        goButton.isEnabled = false
        Updater.download(zip) { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.bar.stopAnimation(nil)
                self.goButton.isEnabled = !self.audio.isEmpty
                switch result {
                case .failure(let e):
                    self.setStatus("Update failed", .systemOrange)
                    self.alert("Couldn't download the update", e.localizedDescription)
                case .success(let newApp):
                    do {
                        try Updater.replaceRunningApp(with: newApp)
                        self.setStatus("Installed — restarting…", .systemGreen)
                        Updater.relaunch()
                    } catch {
                        self.setStatus("Update failed", .systemOrange)
                        let a = NSAlert()
                        a.messageText = "Couldn't install the update"
                        a.informativeText = "\(error.localizedDescription)\n\nYou can download it yourself and replace SongSplit.app by hand."
                        a.addButton(withTitle: "Open Download Page")
                        a.addButton(withTitle: "Cancel")
                        if a.runModal() == .alertFirstButtonReturn { NSWorkspace.shared.open(page) }
                    }
                }
            }
        }
    }

    func setStatus(_ s: String, _ c: NSColor) { status.stringValue = s; status.textColor = c }

    func alert(_ title: String, _ text: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }

    // files dropped on the Dock icon / Finder icon
    func application(_ sender: NSApplication, open urls: [URL]) { accept(urls) }
    func applicationShouldTerminateAfterLastWindowClosed(_ a: NSApplication) -> Bool { true }

    // ---------- helpers
    func label(_ s: String, size: CGFloat, weight: NSFont.Weight,
               secondary: Bool = false) -> NSTextField {
        let t = NSTextField(labelWithString: s)
        t.font = .systemFont(ofSize: size, weight: weight)
        if secondary { t.textColor = .secondaryLabelColor }
        t.lineBreakMode = .byTruncatingMiddle
        return t
    }
    func button(_ title: String, _ sel: Selector) -> NSButton {
        let b = NSButton(title: title, target: self, action: sel)
        b.bezelStyle = .rounded
        return b
    }
    func checkbox(_ title: String) -> NSButton {
        let b = NSButton(checkboxWithTitle: title, target: nil, action: nil)
        return b
    }

    func accept(_ urls: [URL]) {
        for u in urls {
            if u.pathExtension.lowercased() == "csv" { csvs.append(u) }
            else { audio.append(u) }
        }
        refresh()
    }

    func refresh() {
        if audio.isEmpty {
            fileLabel.stringValue = "Drop a WAV here, or on the app icon"
            fileLabel.textColor = .secondaryLabelColor
        } else {
            fileLabel.stringValue = audio.map { $0.lastPathComponent }
                                         .joined(separator: "   •   ")
            fileLabel.textColor = .labelColor
        }
        csvLabel.stringValue = csvs.isEmpty
            ? "No playlist CSV — titles still come from song identification"
            : "Playlist: " + csvs.map { $0.lastPathComponent }.joined(separator: ", ")
        goButton.isEnabled = !audio.isEmpty && task == nil
    }

    @objc func pickAudio() {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = true
        p.canChooseDirectories = false
        p.allowedContentTypes = ["wav", "aif", "aiff", "flac", "mp3", "m4a"]
            .compactMap { UTType(filenameExtension: $0) }
        p.message = "Choose the recording to split"
        if p.runModal() == .OK { audio = p.urls; refresh() }
    }
    @objc func pickCSV() {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = true
        p.allowedContentTypes = [.commaSeparatedText]
        p.message = "Choose a playlist CSV"
        if p.runModal() == .OK { csvs = p.urls; refresh() }
    }
    @objc func clearFiles() { audio = []; csvs = []; refresh() }
    @objc func reveal() {
        if let d = outDir {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: d)
        }
    }

    func append(_ s: String, color: NSColor? = nil) {
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
            .foregroundColor: color ?? NSColor.labelColor]
        logView.textStorage?.append(NSAttributedString(string: s, attributes: attrs))
        logView.scrollToEndOfDocument(nil)
    }

    // ---------- run
    @objc func start() {
        guard task == nil, let first = audio.first else { return }
        logView.string = ""
        outDir = nil
        revealButton.isEnabled = false
        goButton.isEnabled = false
        stopButton.isEnabled = true
        bar.startAnimation(nil)
        status.stringValue = "Working…"
        status.textColor = .labelColor
        runOne(index: 0, url: first)
    }

    func runOne(index: Int, url: URL) {
        if audio.count > 1 {
            append("\n=== \(index + 1)/\(audio.count)  \(url.lastPathComponent) ===\n",
                   color: .secondaryLabelColor)
        }
        var args = ["-u", SPLITTER, url.path] + csvs.map { $0.path }
        if dryBox.state == .on { args.append("--dry-run") }
        if offlineBox.state == .on { args.append("--no-shazam") }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: PY)
        p.arguments = args
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        task = p

        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty, let s = String(data: d, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                var color: NSColor? = nil
                if s.contains("**") || s.lowercased().contains("error") { color = .systemOrange }
                else if s.contains("->") || s.range(of: #"^\s+\d+\."#,
                                                    options: .regularExpression) != nil {
                    color = .systemTeal
                }
                self?.append(s, color: color)
                if let r = s.range(of: "written to: ") {
                    self?.outDir = String(s[r.upperBound...])
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                }
            }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self else { return }
                pipe.fileHandleForReading.readabilityHandler = nil
                self.task = nil
                let next = index + 1
                if proc.terminationStatus == 0 && next < self.audio.count {
                    self.runOne(index: next, url: self.audio[next])
                } else {
                    self.finish(ok: proc.terminationStatus == 0)
                }
            }
        }
        do { try p.run() } catch {
            append("could not start: \(error)\n", color: .systemRed)
            finish(ok: false)
        }
    }

    func finish(ok: Bool) {
        bar.stopAnimation(nil)
        stopButton.isEnabled = false
        goButton.isEnabled = !audio.isEmpty
        status.stringValue = ok ? "Finished" : "Stopped"
        status.textColor = ok ? .systemGreen : .systemOrange
        revealButton.isEnabled = (outDir != nil)
    }

    @objc func stop() {
        task?.terminate()
        append("\nstopping…\n", color: .systemOrange)
    }
}

// MARK: - launch

let app = NSApplication.shared
// songsplit.py sits next to the .app bundle
let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
let bundleDir = exe.deletingLastPathComponent()   // Contents/MacOS
let appDir = bundleDir.deletingLastPathComponent().deletingLastPathComponent()
SPLITTER = appDir.deletingLastPathComponent()
    .appendingPathComponent("songsplit.py").path
if !FileManager.default.fileExists(atPath: SPLITTER) {
    SPLITTER = Bundle.main.path(forResource: "songsplit", ofType: "py") ?? SPLITTER
}

let controller = Controller()
app.delegate = controller
app.setActivationPolicy(.regular)

let menu = NSMenu()
let appItem = NSMenuItem()
menu.addItem(appItem)
let appMenu = NSMenu()
let aboutItem = NSMenuItem(title: "About SongSplit", action: #selector(Controller.about), keyEquivalent: "")
aboutItem.target = controller
appMenu.addItem(aboutItem)
let updateItem = NSMenuItem(title: "Check for Updates…", action: #selector(Controller.checkForUpdatesClicked), keyEquivalent: "")
updateItem.target = controller
appMenu.addItem(updateItem)
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(withTitle: "Hide SongSplit", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
appMenu.addItem(withTitle: "Quit SongSplit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appItem.submenu = appMenu
let editItem = NSMenuItem()
menu.addItem(editItem)
let editMenu = NSMenu(title: "Edit")
editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
editItem.submenu = editMenu
app.mainMenu = menu

app.run()
