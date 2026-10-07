// Reads a WAV's tags the way Mac apps do (AVFoundation and AudioToolbox) and
// fails unless the expected title and artist come back. Run by the Build
// workflow on a WAV whose only metadata is SongSplit's ID3 chunk.
//
//     swift scripts/check_tags_macos.swift FILE.wav "Title" "Artist"
import AVFoundation
import AudioToolbox

let args = CommandLine.arguments
guard args.count == 4 else { print("usage: check_tags_macos FILE TITLE ARTIST"); exit(2) }
let url = URL(fileURLWithPath: args[1])
let (wantTitle, wantArtist) = (args[2], args[3])

let asset = AVURLAsset(url: url)
var av: [String: String] = [:]
for item in asset.commonMetadata {
    if let key = item.commonKey?.rawValue, let value = item.stringValue { av[key] = value }
}
print("AVFoundation:", av)

var info: [String: Any] = [:]
var fileID: AudioFileID?
if AudioFileOpenURL(url as CFURL, .readPermission, 0, &fileID) == noErr, let fileID = fileID {
    var size = UInt32(MemoryLayout<CFDictionary?>.size)
    var dict: Unmanaged<CFDictionary>?
    if AudioFileGetProperty(fileID, kAudioFilePropertyInfoDictionary, &size, &dict) == noErr,
       let d = dict?.takeRetainedValue() as? [String: Any] {
        info = d
    }
    AudioFileClose(fileID)
}
print("AudioToolbox:", info.filter { $0.key != "approximate duration in seconds" })

var ok = true
if av["title"] != wantTitle { print("FAIL: AVFoundation title is \(av["title"] ?? "missing")"); ok = false }
if av["artist"] != wantArtist { print("FAIL: AVFoundation artist is \(av["artist"] ?? "missing")"); ok = false }
print(ok ? "OK: macOS reads the ID3 tag" : "macOS could not read the ID3 tag")
exit(ok ? 0 : 1)
