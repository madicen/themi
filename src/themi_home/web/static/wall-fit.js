// F58c (Michael's bug #249, "on the wall, the frame goes off the bottom"): the wall is one
// screen tall, so a column holds only what fits. The items that don't fit, from the end of
// the last section first, are hidden and counted into that section's "+N more" (on top of
// the server's own count). Done items' "N done" line and the column's foot always stay.
//
// `fitColumn` is the arithmetic, kept apart from the page so a test can run it:
//   sections: [{items: [height, ...], more: n}], other: height of everything else,
//   room: the column body's height, moreHeight: one "+N more" button's height.
// It returns, for each section, how many items to show and the "+N more" to say.
// F65c (Michael's bug #283, "It says there are 2 more, but that's just a lie"): a section may
// also say which items are done (`done`, struck through, at its end) and its "N done" count
// (`folded`). A done item that doesn't fit goes into "N done", never "+N more", which counts
// only what's still to do; `folded` comes back for those sections. `foldHeight`: the "N done"
// line's height, for when it has to appear.
(function (root) {
  "use strict";
  function fitColumn(sections, other, room, moreHeight, foldHeight) {
    foldHeight = foldHeight || 0;
    var out = sections.map(function (s) {
      var o = { shown: s.items.length, more: s.more || 0 };
      if (s.done) o.folded = s.folded || 0;
      return o;
    });
    function used() {
      var total = other;
      out.forEach(function (o, i) {
        for (var k = 0; k < o.shown; k++) total += sections[i].items[k];
        if (o.more > 0) total += moreHeight;
        if (o.folded > 0 && !(sections[i].folded > 0)) total += foldHeight;
      });
      return total;
    }
    for (var i = out.length - 1; i >= 0; i--) {
      while (out[i].shown > 0 && used() > room) {
        out[i].shown -= 1;
        var done = sections[i].done;
        if (done && done[out[i].shown]) out[i].folded += 1;
        else out[i].more += 1;
      }
    }
    return out;
  }

  function sectionsOf(body) {
    // A section is an <h3>, its <ul> of .wall-entry items, its .wall-more button and its
    // .wall-fold "N done" line (F65c).
    var found = [];
    body.querySelectorAll("ul").forEach(function (list) {
      var more = list.nextElementSibling;
      if (!more || !more.classList.contains("wall-more")) more = null;
      var fold = (more || list).nextElementSibling;
      if (!fold || !fold.classList.contains("wall-fold")) fold = null;
      found.push({ entries: Array.prototype.slice.call(list.querySelectorAll(":scope > .wall-entry")),
                   more: more, fold: fold });
    });
    return found;
  }

  function sayDone(fold, count) {
    if (!fold) return;
    fold.hidden = count <= 0;
    var n = fold.querySelector(".wall-fold-n");
    if (n) n.textContent = String(count);
    else if (count > 0) fold.innerHTML = '<span aria-hidden="true">✓</span> <span class="wall-fold-n">' + count + "</span> done";
  }

  function say(button, count) {
    if (!button) return;
    button.hidden = count <= 0;
    button.textContent = count > 0 ? "+" + count + " more" : "";
  }

  // F63a (Michael's bug #269, the date wrapped onto two lines): the top row's date and time
  // never give way. When the row is too tight, the buttons drop to their icons first, then
  // the weather's "low ... tonight" goes. Everything scales with the frame's width, so this
  // depends only on what the row holds (the longest date, the body double's button).
  var TIGHT = ["wall-top-tight", "wall-top-tighter"];
  function fitTop(doc) {
    var top = doc.querySelector(".wall-top");
    if (!top) return;
    TIGHT.forEach(function (c) { top.classList.remove(c); });
    for (var i = 0; i < TIGHT.length && overfull(top); i++) top.classList.add(TIGHT[i]);
  }
  function overfull(top) {
    if (top.scrollWidth > top.clientWidth + 1) return true;
    var asks = top.querySelector(".wall-asks"), when = top.querySelector(".wall-when");
    if (asks && asks.scrollWidth > asks.clientWidth + 1) return true;
    return !!(when && top.getBoundingClientRect().right < when.getBoundingClientRect().right);
  }

  function fitWall(doc) {
    doc = doc || document;
    fitTop(doc);
    doc.querySelectorAll(".wall-col-body").forEach(function (body) {
      var sections = sectionsOf(body);
      sections.forEach(function (s) {
        s.entries.forEach(function (e) { e.classList.remove("wall-cut"); });
        say(s.more, s.more ? Number(s.more.getAttribute("data-more")) || 0 : 0);
        sayDone(s.fold, s.fold ? Number(s.fold.getAttribute("data-done")) || 0 : 0);
      });
      var room = body.clientHeight;
      if (!room || body.scrollHeight <= room) return;
      var probe = sections.filter(function (s) { return s.more; })[0];
      var moreHeight = 0;
      if (probe) {
        var was = probe.more.hidden;
        probe.more.hidden = false;
        probe.more.textContent = probe.more.textContent || "+1 more";
        moreHeight = probe.more.getBoundingClientRect().height;
        probe.more.hidden = was;
        say(probe.more, Number(probe.more.getAttribute("data-more")) || 0);
      }
      var foldHeight = 0;
      var foldProbe = sections.filter(function (s) { return s.fold; })[0];
      if (foldProbe) {
        var hid = foldProbe.fold.hidden;
        foldProbe.fold.hidden = false;
        foldHeight = foldProbe.fold.getBoundingClientRect().height;
        foldProbe.fold.hidden = hid;
      }
      var heights = sections.map(function (s) {
        var h = { items: s.entries.map(function (e) { return e.getBoundingClientRect().height; }),
                  more: s.more ? Number(s.more.getAttribute("data-more")) || 0 : 0 };
        if (s.fold) {
          h.done = s.entries.map(function (e) { return !!e.querySelector(".wall-item.done"); });
          h.folded = Number(s.fold.getAttribute("data-done")) || 0;
        }
        return h;
      });
      var itemsTotal = 0;
      var moresTotal = 0;
      heights.forEach(function (h) {
        h.items.forEach(function (x) { itemsTotal += x; });
        if (h.more > 0) moresTotal += moreHeight;
      });
      var other = body.scrollHeight - itemsTotal - moresTotal;
      var fitted = fitColumn(heights, other, room, moreHeight, foldHeight);
      fitted.forEach(function (f, i) {
        sections[i].entries.forEach(function (e, k) { e.classList.toggle("wall-cut", k >= f.shown); });
        say(sections[i].more, f.more);
        if (f.folded !== undefined) sayDone(sections[i].fold, f.folded);
      });
    });
  }

  root.themiWallFit = { fitColumn: fitColumn, fitWall: fitWall, fitTop: fitTop };
  if (typeof module !== "undefined" && module.exports) module.exports = root.themiWallFit;
})(typeof window !== "undefined" ? window : globalThis);
