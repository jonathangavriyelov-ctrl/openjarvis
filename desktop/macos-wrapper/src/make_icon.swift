import AppKit
import CoreGraphics

let size = 1024
let out = CommandLine.arguments[1]
let cs = CGColorSpaceCreateDeviceRGB()
let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                    space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
let S = CGFloat(size)
// macOS icon grid: ~824px rounded square centered, radius ~185
let inset: CGFloat = 100
let rect = CGRect(x: inset, y: inset, width: S - 2*inset, height: S - 2*inset)
let path = CGPath(roundedRect: rect, cornerWidth: 185, cornerHeight: 185, transform: nil)

// drop shadow
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 30, color: CGColor(gray: 0, alpha: 0.5))
ctx.addPath(path); ctx.setFillColor(CGColor(red: 0.03, green: 0.04, blue: 0.08, alpha: 1)); ctx.fillPath()
ctx.restoreGState()

ctx.saveGState()
ctx.addPath(path); ctx.clip()
// background vertical gradient
let bg = CGGradient(colorsSpace: cs, colors: [
    CGColor(red: 0.07, green: 0.09, blue: 0.18, alpha: 1),
    CGColor(red: 0.02, green: 0.03, blue: 0.07, alpha: 1)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: S - inset), end: CGPoint(x: 0, y: inset), options: [])
let c = CGPoint(x: S/2, y: S/2)
// outer glow
let glow = CGGradient(colorsSpace: cs, colors: [
    CGColor(red: 0.2, green: 0.75, blue: 1, alpha: 0.55),
    CGColor(red: 0.1, green: 0.35, blue: 0.9, alpha: 0.18),
    CGColor(red: 0.05, green: 0.1, blue: 0.3, alpha: 0)] as CFArray, locations: [0, 0.45, 1])!
ctx.drawRadialGradient(glow, startCenter: c, startRadius: 0, endCenter: c, endRadius: 420, options: [])
// rings
for (r, a, w) in [(300.0, 0.9, 10.0), (345.0, 0.35, 4.0), (250.0, 0.25, 3.0)] {
    ctx.setStrokeColor(CGColor(red: 0.45, green: 0.88, blue: 1, alpha: a))
    ctx.setLineWidth(w)
    ctx.setShadow(offset: .zero, blur: 24, color: CGColor(red: 0.3, green: 0.8, blue: 1, alpha: 1))
    ctx.strokeEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2*r, height: 2*r))
}
// arc segments on the main ring
ctx.setLineWidth(22); ctx.setLineCap(.round)
ctx.setStrokeColor(CGColor(red: 0.7, green: 0.95, blue: 1, alpha: 1))
for s in stride(from: 0.0, to: 360.0, by: 90.0) {
    ctx.addArc(center: c, radius: 300, startAngle: CGFloat((s + 20) * .pi / 180),
               endAngle: CGFloat((s + 60) * .pi / 180), clockwise: false)
    ctx.strokePath()
}
ctx.restoreGState()

// "J"
let ns = NSGraphicsContext(cgContext: ctx, flipped: false)
NSGraphicsContext.current = ns
let font = NSFont.systemFont(ofSize: 380, weight: .semibold)
let shadow = NSShadow(); shadow.shadowBlurRadius = 40; shadow.shadowOffset = .zero
shadow.shadowColor = NSColor(calibratedRed: 0.3, green: 0.85, blue: 1, alpha: 1)
let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.white, .shadow: shadow]
let str = NSAttributedString(string: "J", attributes: attrs)
let b = str.boundingRect(with: NSSize(width: 1000, height: 1000), options: [.usesLineFragmentOrigin, .usesFontLeading])
let glyph = str.size()
str.draw(at: NSPoint(x: c.x - glyph.width/2 - b.minX/2, y: c.y - glyph.height/2 + 10))
str.draw(at: NSPoint(x: c.x - glyph.width/2 - b.minX/2, y: c.y - glyph.height/2 + 10))

let img = ctx.makeImage()!
let rep = NSBitmapImageRep(cgImage: img)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("wrote \(out)")
