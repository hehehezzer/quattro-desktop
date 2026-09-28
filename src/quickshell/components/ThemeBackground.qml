import Quickshell
import Quickshell.Wayland
import QtQuick
import "../theme" as QuattroTheme

PanelWindow {
    id: root

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    color: QuattroTheme.Theme.background
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    WlrLayershell.namespace: "quattro-theme-background"

    // Local artwork remains supported. Without it, Quattro ships a complete
    // theme-aware background rather than falling back to a black canvas.
    property string wallpaperDirectory: Quickshell.env("QUATTRO_WALLPAPER_DIR") || ""

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: QuattroTheme.Theme.canvasTop }
            GradientStop { position: 0.58; color: QuattroTheme.Theme.background }
            GradientStop { position: 1.0; color: QuattroTheme.Theme.canvasBottom }
        }
    }

    // Broad static planes give the desktop depth while remaining cheaper than
    // blur, shaders, particles, or continuously animated effects.
    Rectangle {
        width: parent.width * 0.72
        height: Math.max(220, parent.height * 0.28)
        x: -width * 0.16
        y: parent.height * 0.18
        rotation: -8
        color: QuattroTheme.Theme.ambientPrimary
        opacity: 0.10
    }

    Rectangle {
        width: parent.width * 0.58
        height: Math.max(180, parent.height * 0.22)
        x: parent.width - width * 0.78
        y: parent.height * 0.68
        rotation: 7
        color: QuattroTheme.Theme.ambientSecondary
        opacity: 0.10
    }

    Canvas {
        id: atmosphere
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        function repaint() {
            requestPaint()
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.save()
            ctx.strokeStyle = QuattroTheme.Theme.canvasLine
            ctx.fillStyle = QuattroTheme.Theme.canvasLine
            ctx.globalAlpha = QuattroTheme.Theme.motifOpacity
            ctx.lineWidth = 1

            const step = QuattroTheme.Theme.motifStep
            const motif = QuattroTheme.Theme.motif

            if (motif === "draft") {
                for (let x = step; x < width; x += step) {
                    ctx.globalAlpha = x % (step * 4) === 0
                        ? QuattroTheme.Theme.motifOpacity
                        : QuattroTheme.Theme.motifOpacity * 0.34
                    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke()
                }
                for (let y = step; y < height; y += step) {
                    ctx.globalAlpha = y % (step * 4) === 0
                        ? QuattroTheme.Theme.motifOpacity
                        : QuattroTheme.Theme.motifOpacity * 0.34
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
                }
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity * 1.25
                ctx.beginPath(); ctx.moveTo(width * 0.06, height * 0.76)
                ctx.lineTo(width * 0.48, height * 0.34)
                ctx.lineTo(width * 0.92, height * 0.34); ctx.stroke()
            } else if (motif === "contour") {
                for (let i = 0; i < 7; i++) {
                    ctx.globalAlpha = QuattroTheme.Theme.motifOpacity * (1 - i * 0.08)
                    ctx.beginPath()
                    ctx.ellipse(width * 0.78, height * 0.74,
                        width * (0.13 + i * 0.055), height * (0.10 + i * 0.042),
                        -0.18, 0, Math.PI * 2)
                    ctx.stroke()
                }
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity * 0.52
                ctx.beginPath(); ctx.moveTo(0, height * 0.31)
                ctx.bezierCurveTo(width * 0.24, height * 0.21,
                    width * 0.42, height * 0.47, width * 0.68, height * 0.32)
                ctx.stroke()
            } else if (motif === "scan") {
                for (let y = step; y < height; y += step) {
                    ctx.globalAlpha = y % (step * 4) === 0
                        ? QuattroTheme.Theme.motifOpacity
                        : QuattroTheme.Theme.motifOpacity * 0.24
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
                }
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity
                for (let x = width * 0.12; x < width; x += width * 0.19) {
                    ctx.fillRect(x, height * 0.17, 2, height * 0.66)
                    ctx.fillRect(x - 3, height * 0.17, 8, 1)
                    ctx.fillRect(x - 3, height * 0.83, 8, 1)
                }
            } else if (motif === "transit") {
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity
                const vanishingX = width * 0.68
                const horizonY = height * 0.42
                for (let x = -width * 0.1; x < width * 1.2; x += step) {
                    ctx.beginPath(); ctx.moveTo(x, height); ctx.lineTo(vanishingX, horizonY); ctx.stroke()
                }
                for (let i = 0; i < 9; i++) {
                    const p = i / 9
                    const y = horizonY + (height - horizonY) * p * p
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
                }
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity * 1.3
                ctx.fillRect(width * 0.08, height * 0.17, width * 0.22, 2)
            } else {
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity
                const cx = width * 0.77
                const cy = height * 0.44
                const radius = Math.min(width, height) * 0.23
                ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.stroke()
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity * 0.44
                for (let i = 1; i < 5; i++) {
                    ctx.beginPath(); ctx.arc(cx, cy, radius + i * 34, -0.62, 2.46); ctx.stroke()
                }
                ctx.globalAlpha = QuattroTheme.Theme.motifOpacity
                ctx.beginPath(); ctx.moveTo(cx - radius * 1.7, cy)
                ctx.lineTo(cx + radius * 1.7, cy); ctx.stroke()
            }
            ctx.restore()
        }

        Connections {
            target: QuattroTheme.Theme
            function onCurrentChanged() { atmosphere.requestPaint() }
            function onCanvasLineChanged() { atmosphere.requestPaint() }
        }
    }

    Image {
        id: wallpaper
        anchors.fill: parent
        source: root.wallpaperDirectory === "" ? ""
            : "file://" + root.wallpaperDirectory + "/"
                + QuattroTheme.Theme.current + ".png"
        fillMode: Image.PreserveAspectCrop
        horizontalAlignment: Image.AlignHCenter
        verticalAlignment: Image.AlignVCenter
        asynchronous: true
        cache: true
        smooth: true
        mipmap: true
        opacity: status === Image.Ready ? 0.88 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: QuattroTheme.Theme.motionAtmosphere
                easing.type: Easing.OutCubic
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: wallpaper.status === Image.Ready
        color: QuattroTheme.Theme.background
        opacity: 0.12
    }
}
