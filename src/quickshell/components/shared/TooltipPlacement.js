.pragma library

var owner = null;
function claim(candidate) {
    if (owner && owner !== candidate) owner.dismiss();
    owner = candidate;
}
function release(candidate) { if (owner === candidate) owner = null; }
function overlaps(a, b) {
    return a.x < b.x + b.width && a.x + a.width > b.x
        && a.y < b.y + b.height && a.y + a.height > b.y;
}
// Panel anchors/margins are monitor-local; Qt mapToGlobal lacks layer positions.
function panelOrigin(anchors, margins, size, viewport) {
    return {
        x: anchors.left ? margins.left : anchors.right ? viewport.width-size.width-margins.right : (viewport.width-size.width)/2,
        y: anchors.top ? margins.top : anchors.bottom ? viewport.height-size.height-margins.bottom : (viewport.height-size.height)/2
    };
}
// All coordinates are logical pixels relative to the source monitor.
function place(target, pointer, size, viewport, gap) {
    if (!overlaps(target, {x:0, y:0, width:viewport.width, height:viewport.height})) return null;
    var inset = 8;
    var maxX = viewport.width - size.width - inset;
    var maxY = viewport.height - size.height - inset;
    if (maxX < inset || maxY < inset) return null;
    var clampX = function(x) { return Math.max(inset, Math.min(maxX, x)); };
    var clampY = function(y) { return Math.max(inset, Math.min(maxY, y)); };
    var candidates = [
        {x: clampX(pointer.x + gap), y: target.y + target.height + gap},
        {x: clampX(pointer.x + gap), y: target.y - size.height - gap},
        {x: target.x + target.width + gap, y: clampY(pointer.y + gap)},
        {x: target.x - size.width - gap, y: clampY(pointer.y + gap)}
    ];
    var exclusion = {x: pointer.x - gap, y: pointer.y - gap, width: gap * 2, height: gap * 2};
    for (var i = 0; i < candidates.length; ++i) {
        var c = candidates[i];
        var rect = {x:c.x, y:c.y, width:size.width, height:size.height};
        if (c.x >= inset && c.y >= inset && c.x <= maxX && c.y <= maxY
            && !overlaps(rect, target) && !overlaps(rect, exclusion)) return c;
    }
    return null;
}
