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

// MARK: - drawing helpers

func symbol(_ name: String, _ size: CGFloat, _ weight: NSFont.Weight = .regular) -> NSImage? {
    NSImage(systemSymbolName: name, accessibilityDescription: nil)?
        .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: size, weight: weight))
}

/// A flat rounded card. Colours are resolved in draw(_:), so it follows light/dark mode.
class Card: NSView {
    var fillColor: NSColor = .clear { didSet { needsDisplay = true } }
    var strokeColor: NSColor? = nil { didSet { needsDisplay = true } }
    var cornerRadius: CGFloat = 12 { didSet { layer?.cornerRadius = cornerRadius; needsDisplay = true } }

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.cornerRadius = cornerRadius
        layer?.masksToBounds = true
        translatesAutoresizingMaskIntoConstraints = false
    }
    required init?(coder: NSCoder) { fatalError() }
    override var mouseDownCanMoveWindow: Bool { false }

    override func draw(_ r: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5),
                                xRadius: cornerRadius, yRadius: cornerRadius)
        fillColor.setFill()
        path.fill()
        if let s = strokeColor {
            s.setStroke()
            path.lineWidth = 1
            path.stroke()
        }
    }
}

/// The app icon shown in the window header: a waveform on an accent-coloured gradient tile.
final class IconTile: NSView {
    override init(frame: NSRect) {
        super.init(frame: frame)
        translatesAutoresizingMaskIntoConstraints = false
        let glyph = NSImageView()
        glyph.image = symbol("waveform", 24, .bold)
        glyph.contentTintColor = .white
        glyph.translatesAutoresizingMaskIntoConstraints = false
        addSubview(glyph)
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 48),
            heightAnchor.constraint(equalToConstant: 48),
            glyph.centerXAnchor.constraint(equalTo: centerXAnchor),
            glyph.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError() }
    override var mouseDownCanMoveWindow: Bool { false }

    override func draw(_ r: NSRect) {
        let accent = NSColor.controlAccentColor
        let top = accent.blended(withFraction: 0.22, of: .white) ?? accent
        let bottom = accent.blended(withFraction: 0.22, of: .black) ?? accent
        let path = NSBezierPath(roundedRect: bounds, xRadius: 12, yRadius: 12)
        NSGradient(starting: top, ending: bottom)?.draw(in: path, angle: -90)
        NSColor.black.withAlphaComponent(0.18).setStroke()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 12, yRadius: 12).stroke()
    }
}

/// Coloured dot used in the status pill.
final class Dot: NSView {
    var color: NSColor = .tertiaryLabelColor { didSet { needsDisplay = true } }
    override init(frame: NSRect) {
        super.init(frame: frame)
        translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([widthAnchor.constraint(equalToConstant: 8),
                                     heightAnchor.constraint(equalToConstant: 8)])
    }
    required init?(coder: NSCoder) { fatalError() }
    override func draw(_ r: NSRect) {
        color.setFill()
        NSBezierPath(ovalIn: bounds).fill()
    }
}

/// "● Ready" pill: a dot (or a spinner while busy) and a short message.
final class StatusPill: Card {
    private let dot = Dot()
    private let spinner = NSProgressIndicator()
    private let text = NSTextField(labelWithString: "Ready")

    override init(frame: NSRect) {
        super.init(frame: frame)
        cornerRadius = 13
        fillColor = NSColor.labelColor.withAlphaComponent(0.06)

        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isIndeterminate = true
        spinner.isDisplayedWhenStopped = false
        spinner.isHidden = true
        spinner.translatesAutoresizingMaskIntoConstraints = false

        text.font = .systemFont(ofSize: 12, weight: .medium)
        text.textColor = .secondaryLabelColor
        text.lineBreakMode = .byTruncatingTail
        text.maximumNumberOfLines = 1
        text.translatesAutoresizingMaskIntoConstraints = false

        let row = NSStackView(views: [dot, spinner, text])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 7
        row.translatesAutoresizingMaskIntoConstraints = false
        addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            row.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            row.centerYAnchor.constraint(equalTo: centerYAnchor),
            heightAnchor.constraint(equalToConstant: 26),
        ])
    }
    required init?(coder: NSCoder) { fatalError() }

    func set(_ message: String, _ color: NSColor, busy: Bool = false) {
        text.stringValue = message
        text.textColor = busy ? .labelColor : color
        dot.color = color
        dot.isHidden = busy
        spinner.isHidden = !busy
        if busy { spinner.startAnimation(nil) } else { spinner.stopAnimation(nil) }
    }
}

// MARK: - drop target

final class DropView: NSView {
    var onDrop: (([URL]) -> Void)?
    var onClick: (() -> Void)?
    var hasFiles = false { didSet { needsDisplay = true } }
    private var lit = false { didSet { needsDisplay = true } }

    override init(frame: NSRect) {
        super.init(frame: frame)
        registerForDraggedTypes([.fileURL])
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
    }
    required init?(coder: NSCoder) { fatalError() }
    override var mouseDownCanMoveWindow: Bool { false }

    private func urls(_ sender: NSDraggingInfo) -> [URL] {
        (sender.draggingPasteboard.readObjects(forClasses: [NSURL.self],
            options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
    }
    override func draggingEntered(_ s: NSDraggingInfo) -> NSDragOperation {
        lit = !urls(s).isEmpty
        return lit ? .copy : []
    }
    override func draggingExited(_ s: NSDraggingInfo?) { lit = false }
    override func performDragOperation(_ s: NSDraggingInfo) -> Bool {
        lit = false
        let u = urls(s)
        if u.isEmpty { return false }
        onDrop?(u)
        return true
    }
    // Clicking the empty zone opens the file chooser, like a web drop zone.
    override func mouseDown(with e: NSEvent) {
        if hasFiles { super.mouseDown(with: e) } else { onClick?() }
    }

    override func draw(_ r: NSRect) {
        let accent = NSColor.controlAccentColor
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 1, dy: 1), xRadius: 14, yRadius: 14)
        let fill: NSColor
        if lit { fill = accent.withAlphaComponent(0.16) }
        else if hasFiles { fill = accent.withAlphaComponent(0.07) }
        else { fill = NSColor.labelColor.withAlphaComponent(0.035) }
        fill.setFill()
        path.fill()

        path.lineWidth = lit ? 2 : 1
        if !lit && !hasFiles {
            let dash: [CGFloat] = [6, 4]
            path.setLineDash(dash, count: dash.count, phase: 0)
        }
        let stroke: NSColor
        if lit { stroke = accent }
        else if hasFiles { stroke = accent.withAlphaComponent(0.55) }
        else { stroke = NSColor.separatorColor }
        stroke.setStroke()
        path.stroke()
    }
}

// MARK: - app

final class Controller: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var drop: DropView!
    var dropIcon: NSImageView!
    var fileLabel: NSTextField!
    var csvLabel: NSTextField!
    var audioButton: NSButton!
    var csvButton: NSButton!
    var clearButton: NSButton!
    var status: StatusPill!
    var logView: NSTextView!
    var logPlaceholder: NSTextField!
    var bar: NSProgressIndicator!
    var goButton: NSButton!
    var stopButton: NSButton!
    var revealButton: NSButton!
    var dryBox: NSButton!
    var offlineBox: NSButton!
    var artistNameBox: NSButton!
    var artistFolderBox: NSButton!

    var audio: [URL] = []
    var csvs: [URL] = []
    var task: Process?
    var outDir: String?

    // ---------- layout
    func applicationDidFinishLaunching(_ n: Notification) {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 660),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                         backing: .buffered, defer: false)
        w.title = "SongSplit"
        w.titlebarAppearsTransparent = true
        w.titleVisibility = .hidden
        w.minSize = NSSize(width: 680, height: 560)
        w.center()
        w.setFrameAutosaveName("SongSplitMain")
        window = w

        let root = NSView()
        w.contentView = root

        // ----- header: icon tile, title + tagline, version + update button
        let tile = IconTile()

        let title = label("SongSplit", size: 26, weight: .bold)
        if let d = title.font?.fontDescriptor.withDesign(.rounded) {
            title.font = NSFont(descriptor: d, size: 26) ?? title.font
        }
        let sub = label("Split one long recording into separate, tagged songs.",
                        size: 13, weight: .regular, color: .secondaryLabelColor)
        let titleCol = vstack([title, sub], spacing: 2, alignment: .leading)

        let ver = label("Version \(BuildInfo.version) · build \(BuildInfo.build)",
                        size: 11, weight: .medium, color: .secondaryLabelColor)
        ver.alignment = .right
        let built = label("\(BuildInfo.date) · \(BuildInfo.commit)",
                          size: 10, weight: .regular, color: .tertiaryLabelColor)
        built.alignment = .right
        built.font = NSFont.monospacedDigitSystemFont(ofSize: 10, weight: .regular)
        let upd = button("Check for Updates…", symbol: "arrow.triangle.2.circlepath",
                         #selector(checkForUpdatesClicked))
        upd.controlSize = .small
        upd.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        let verCol = vstack([ver, built, upd], spacing: 3, alignment: .trailing)
        verCol.setCustomSpacing(8, after: built)

        let header = hstack([tile, titleCol, spacer(), verCol], spacing: 14, alignment: .centerY)

        // ----- drop zone
        drop = DropView()
        drop.onDrop = { [weak self] urls in self?.accept(urls) }
        drop.onClick = { [weak self] in self?.pickAudio() }

        dropIcon = NSImageView()
        dropIcon.translatesAutoresizingMaskIntoConstraints = false
        dropIcon.imageScaling = .scaleNone

        fileLabel = label("", size: 14, weight: .semibold)
        fileLabel.alignment = .center
        fileLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        csvLabel = label("", size: 11.5, weight: .regular, color: .secondaryLabelColor)
        csvLabel.alignment = .center
        csvLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        audioButton = button("Choose Audio…", symbol: "folder", #selector(pickAudio))
        csvButton = button("Add Playlist CSV…", symbol: "doc.text", #selector(pickCSV))
        clearButton = button("Clear", symbol: "xmark.circle", #selector(clearFiles))
        let pickRow = hstack([audioButton, csvButton, clearButton], spacing: 8, alignment: .centerY)

        let dropStack = vstack([dropIcon, fileLabel, csvLabel, pickRow], spacing: 4, alignment: .centerX)
        dropStack.setCustomSpacing(10, after: dropIcon)
        dropStack.setCustomSpacing(14, after: csvLabel)
        drop.addSubview(dropStack)
        NSLayoutConstraint.activate([
            drop.heightAnchor.constraint(equalToConstant: 172),
            dropStack.centerXAnchor.constraint(equalTo: drop.centerXAnchor),
            dropStack.centerYAnchor.constraint(equalTo: drop.centerYAnchor),
            dropStack.widthAnchor.constraint(lessThanOrEqualTo: drop.widthAnchor, constant: -40),
        ])

        // ----- options (naming choices are remembered between launches)
        artistNameBox = checkbox("Artist in file name (Artist - Title.wav)", remember: "SongSplitArtistInName")
        artistFolderBox = checkbox("Folder per artist", remember: "SongSplitArtistFolders")
        dryBox = checkbox("Preview only — write nothing")
        offlineBox = checkbox("Skip song identification (offline)")
        let options = vstack([
            hstack([artistNameBox, artistFolderBox, spacer()], spacing: 24, alignment: .centerY),
            hstack([dryBox, offlineBox, spacer()], spacing: 24, alignment: .centerY),
        ], spacing: 8, alignment: .leading)
        for row in options.arrangedSubviews {
            row.widthAnchor.constraint(equalTo: options.widthAnchor).isActive = true
        }

        // ----- actions + status
        goButton = button("Split", symbol: "scissors", #selector(start))
        goButton.keyEquivalent = "\r"
        goButton.controlSize = .large
        goButton.font = .systemFont(ofSize: 13, weight: .semibold)

        stopButton = button("Stop", symbol: "stop.fill", #selector(stop))
        stopButton.controlSize = .large
        stopButton.isEnabled = false

        revealButton = button("Show in Finder", symbol: "folder", #selector(reveal))
        revealButton.controlSize = .large
        revealButton.isEnabled = false

        status = StatusPill()
        status.set("Ready", .tertiaryLabelColor)

        let actions = hstack([goButton, stopButton, revealButton, spacer(), status],
                             spacing: 8, alignment: .centerY)
        actions.setCustomSpacing(16, after: stopButton)

        bar = NSProgressIndicator()
        bar.isIndeterminate = true
        bar.style = .bar
        bar.controlSize = .small
        bar.isDisplayedWhenStopped = false
        bar.translatesAutoresizingMaskIntoConstraints = false

        // ----- log card
        let logCard = Card()
        logCard.cornerRadius = 10
        logCard.fillColor = .textBackgroundColor
        logCard.strokeColor = .separatorColor
        logCard.setContentHuggingPriority(NSLayoutConstraint.Priority(1), for: .vertical)

        let scroll = NSScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        scroll.drawsBackground = false
        logView = NSTextView(frame: NSRect(x: 0, y: 0, width: 700, height: 300))
        logView.isEditable = false
        logView.drawsBackground = false
        logView.font = NSFont.monospacedSystemFont(ofSize: 11.5, weight: .regular)
        logView.textContainerInset = NSSize(width: 12, height: 12)
        logView.isVerticallyResizable = true
        logView.isHorizontallyResizable = false
        logView.minSize = NSSize(width: 0, height: 0)
        logView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude,
                                 height: CGFloat.greatestFiniteMagnitude)
        logView.textContainer?.widthTracksTextView = true
        logView.autoresizingMask = [.width]
        scroll.documentView = logView
        logCard.addSubview(scroll)

        logPlaceholder = label("Progress and results will appear here.",
                               size: 12, weight: .regular, color: .tertiaryLabelColor)
        logPlaceholder.alignment = .center
        logCard.addSubview(logPlaceholder)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: logCard.leadingAnchor, constant: 1),
            scroll.trailingAnchor.constraint(equalTo: logCard.trailingAnchor, constant: -1),
            scroll.topAnchor.constraint(equalTo: logCard.topAnchor, constant: 1),
            scroll.bottomAnchor.constraint(equalTo: logCard.bottomAnchor, constant: -1),
            logPlaceholder.centerXAnchor.constraint(equalTo: logCard.centerXAnchor),
            logPlaceholder.centerYAnchor.constraint(equalTo: logCard.centerYAnchor),
        ])

        // ----- assemble
        let column = vstack([header, drop, options, actions, bar, logCard],
                            spacing: 16, alignment: .leading)
        column.setCustomSpacing(22, after: header)
        column.setCustomSpacing(12, after: drop)
        column.setCustomSpacing(10, after: actions)
        column.setCustomSpacing(10, after: bar)
        root.addSubview(column)
        var cs = [
            column.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 28),
            column.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -28),
            column.topAnchor.constraint(equalTo: root.topAnchor, constant: 44),
            column.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -24),
        ]
        for row in column.arrangedSubviews {
            cs.append(row.widthAnchor.constraint(equalTo: column.widthAnchor))
        }
        NSLayoutConstraint.activate(cs)

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
        if manual { setStatus("Checking for updates…", .controlAccentColor, busy: true) }
        Updater.fetchLatest { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch result {
                case .failure(let e):
                    guard manual else { return }
                    self.setStatus("Ready", .tertiaryLabelColor)
                    self.alert("Couldn't check for updates", e.localizedDescription)
                case .success(let r):
                    if Updater.isNewer(r.version, than: BuildInfo.version) {
                        if manual { self.setStatus("Update available", .controlAccentColor) }
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
        setStatus("Downloading update…", .controlAccentColor, busy: true)
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

    func setStatus(_ s: String, _ c: NSColor, busy: Bool = false) { status.set(s, c, busy: busy) }

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
               color: NSColor = .labelColor) -> NSTextField {
        let t = NSTextField(labelWithString: s)
        t.font = .systemFont(ofSize: size, weight: weight)
        t.textColor = color
        t.lineBreakMode = .byTruncatingMiddle
        t.maximumNumberOfLines = 1
        t.translatesAutoresizingMaskIntoConstraints = false
        return t
    }
    func button(_ title: String, symbol name: String? = nil, _ sel: Selector) -> NSButton {
        let b = NSButton(title: title, target: self, action: sel)
        b.bezelStyle = .rounded
        if let name = name, let img = symbol(name, 11, .medium) {
            b.image = img
            b.imagePosition = .imageLeading
            b.imageHugsTitle = true
        }
        b.translatesAutoresizingMaskIntoConstraints = false
        return b
    }
    /// Shows on a picker button whether its file has been added: a green check
    /// and "Change…" wording once loaded, the plain symbol and "Choose…" otherwise.
    func mark(_ b: NSButton, loaded: Bool, idle: String, done: String, symbol name: String) {
        b.title = loaded ? done : idle
        guard loaded, let check = symbol("checkmark.circle.fill", 11, .semibold) else {
            b.image = symbol(name, 11, .medium)
            return
        }
        let tinted = NSImage(size: check.size, flipped: false) { rect in
            check.draw(in: rect)
            NSColor.systemGreen.set()
            rect.fill(using: .sourceAtop)
            return true
        }
        tinted.isTemplate = false
        b.image = tinted
    }
    /// A checkbox; with `remember`, its state is stored in UserDefaults under that key.
    func checkbox(_ title: String, remember key: String? = nil) -> NSButton {
        let b = NSButton(checkboxWithTitle: title, target: nil, action: nil)
        b.translatesAutoresizingMaskIntoConstraints = false
        if let key = key {
            b.state = UserDefaults.standard.bool(forKey: key) ? .on : .off
            b.identifier = NSUserInterfaceItemIdentifier(key)
            b.target = self
            b.action = #selector(rememberCheckbox(_:))
        }
        return b
    }
    @objc func rememberCheckbox(_ sender: NSButton) {
        guard let key = sender.identifier?.rawValue else { return }
        UserDefaults.standard.set(sender.state == .on, forKey: key)
    }
    func spacer() -> NSView {
        let v = NSView()
        v.translatesAutoresizingMaskIntoConstraints = false
        v.setContentHuggingPriority(NSLayoutConstraint.Priority(1), for: .horizontal)
        v.setContentCompressionResistancePriority(NSLayoutConstraint.Priority(1), for: .horizontal)
        return v
    }
    func vstack(_ views: [NSView], spacing: CGFloat,
                alignment: NSLayoutConstraint.Attribute) -> NSStackView {
        let s = NSStackView(views: views)
        s.orientation = .vertical
        s.alignment = alignment
        s.spacing = spacing
        s.translatesAutoresizingMaskIntoConstraints = false
        return s
    }
    func hstack(_ views: [NSView], spacing: CGFloat,
                alignment: NSLayoutConstraint.Attribute) -> NSStackView {
        let s = NSStackView(views: views)
        s.orientation = .horizontal
        s.alignment = alignment
        s.spacing = spacing
        s.translatesAutoresizingMaskIntoConstraints = false
        return s
    }

    func accept(_ urls: [URL]) {
        for u in urls {
            if u.pathExtension.lowercased() == "csv" { csvs.append(u) }
            else { audio.append(u) }
        }
        refresh()
    }

    func refresh() {
        drop.hasFiles = !audio.isEmpty
        if audio.isEmpty {
            dropIcon.image = symbol("waveform", 30, .regular)
            dropIcon.contentTintColor = .tertiaryLabelColor
            fileLabel.stringValue = "Drop a recording here"
            fileLabel.textColor = .labelColor
            csvLabel.stringValue = csvs.isEmpty
                ? "WAV, AIFF, FLAC, MP3 or M4A · or drop it on the app icon"
                : "Playlist: " + csvs.map { $0.lastPathComponent }.joined(separator: ", ")
                  + " — now add the recording"
        } else {
            dropIcon.image = symbol("music.note.list", 30, .regular)
            dropIcon.contentTintColor = .controlAccentColor
            let names = audio.map { $0.lastPathComponent }
            fileLabel.stringValue = names.count == 1
                ? names[0]
                : "\(names.count) recordings · " + names.joined(separator: ", ")
            fileLabel.textColor = .labelColor
            csvLabel.stringValue = csvs.isEmpty
                ? "No playlist CSV — titles will come from song identification"
                : "Playlist: " + csvs.map { $0.lastPathComponent }.joined(separator: ", ")
        }
        mark(audioButton, loaded: !audio.isEmpty,
             idle: "Choose Audio…", done: "Change Audio…", symbol: "folder")
        mark(csvButton, loaded: !csvs.isEmpty,
             idle: "Add Playlist CSV…", done: "Change Playlist CSV…", symbol: "doc.text")
        clearButton.isEnabled = !(audio.isEmpty && csvs.isEmpty)
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
        let para = NSMutableParagraphStyle()
        para.lineSpacing = 2
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: 11.5, weight: .regular),
            .foregroundColor: color ?? NSColor.labelColor,
            .paragraphStyle: para]
        logView.textStorage?.append(NSAttributedString(string: s, attributes: attrs))
        logPlaceholder.isHidden = true
        logView.scrollToEndOfDocument(nil)
    }

    // ---------- run
    @objc func start() {
        guard task == nil, let first = audio.first else { return }
        logView.string = ""
        logPlaceholder.isHidden = false
        outDir = nil
        revealButton.isEnabled = false
        goButton.isEnabled = false
        stopButton.isEnabled = true
        bar.startAnimation(nil)
        setStatus("Working…", .controlAccentColor, busy: true)
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
        if artistNameBox.state == .on { args.append("--artist-in-name") }
        if artistFolderBox.state == .on { args.append("--artist-folders") }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: PY)
        p.arguments = args
        // Apps launched from Finder get a minimal PATH; make sure Homebrew's
        // ffmpeg is visible to songsplit.py and the libraries it uses.
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = (["/opt/homebrew/bin", "/usr/local/bin"] + [env["PATH"] ?? "/usr/bin:/bin"])
            .joined(separator: ":")
        p.environment = env
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
        setStatus(ok ? "Finished" : "Stopped", ok ? .systemGreen : .systemOrange)
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
