import QtQuick
import "../../theme" as QuattroTheme

Item {
    id: root
    property var samples: []
    property string field: "cpu"
    property real maximum: 100
    property int windowSeconds: 120
    property bool showAxis: true
    property color strokeColor: QuattroTheme.Theme.textStrong
    readonly property real leftInset: showAxis ? 38 : 1
    readonly property real bottomInset: showAxis ? 18 : 1
    implicitHeight: 150
    onSamplesChanged: graph.requestPaint()
    onMaximumChanged: graph.requestPaint()
    onStrokeColorChanged: graph.requestPaint()
    onFieldChanged: graph.requestPaint()
    onShowAxisChanged: graph.requestPaint()
    onWidthChanged: graph.requestPaint()
    onHeightChanged: graph.requestPaint()

    Repeater {
        model: root.showAxis ? 5 : 0
        Text {
            required property int index
            x: 0
            y: index * (root.height - root.bottomInset - 12) / 4
            width: root.leftInset - 8
            horizontalAlignment: Text.AlignRight
            text: Math.round(root.maximum * (1 - index / 4))
            color: QuattroTheme.Theme.textMuted
            font.family: QuattroTheme.Theme.fontFamily
            font.pixelSize: 12
        }
    }
    Canvas {
        id: graph
        anchors.fill: parent
        renderStrategy: Canvas.Immediate
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const left = root.leftInset, top = 6, right = width - 1, bottom = height - root.bottomInset
            const w = right - left, h = bottom - top
            if (w <= 0 || h <= 0) return
            ctx.strokeStyle = QuattroTheme.Theme.border
            ctx.lineWidth = 1
            ctx.beginPath()
            for (let i = 0; i <= 4; i++) {
                const y = top + h * i / 4
                ctx.moveTo(left, y); ctx.lineTo(right, y)
            }
            if (root.showAxis) {
                for (let i = 0; i <= 6; i++) {
                    const x = left + w * i / 6
                    ctx.moveTo(x, top); ctx.lineTo(x, bottom)
                }
            }
            ctx.stroke()
            const values = root.samples
            if (!values.length || root.maximum <= 0) return
            const end = values[values.length - 1].time, start = end - root.windowSeconds * 1000
            ctx.strokeStyle = root.strokeColor
            ctx.lineWidth = 1.5
            ctx.beginPath()
            let connected = false, previous = 0
            for (const point of values) {
                const value = point[root.field]
                if (point.time < start || value === null || typeof value !== "number" || !isFinite(value)) {
                    connected = false
                    continue
                }
                const x = left + (point.time - start) / (end - start) * w
                const y = bottom - Math.max(0, Math.min(root.maximum, value)) / root.maximum * h
                if (connected && point.time - previous <= 6000) ctx.lineTo(x, y)
                else ctx.moveTo(x, y)
                // A single valid sample remains visible without inventing a segment.
                ctx.fillStyle = root.strokeColor
                ctx.fillRect(x - 1, y - 1, 2, 2)
                connected = true
                previous = point.time
            }
            ctx.stroke()
        }
    }
    Connections {
        target: QuattroTheme.Theme
        function onBorderChanged() { graph.requestPaint() }
    }
}
