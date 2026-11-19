// F49f (bug #223): what the phone's lock screen and Control Centre show while Themi's music
// plays. Without it iOS showed "Cooking · Themi" with the page's old home-screen icon. Here:
// the track, "Themi", the room (Cooking, Body double) and Themi's current icon, and the lock
// screen's play and pause drive the page's own player.
(function () {
  "use strict";
  window.themiNowPlaying = function (box, title, actions) {
    if (!("mediaSession" in navigator) || typeof window.MediaMetadata !== "function") return;
    var art = (box && box.dataset.artwork) || "";
    var small = (box && box.dataset.artworkSmall) || "";
    var artwork = [];
    if (small) artwork.push({ src: small, sizes: "192x192", type: "image/png" });
    if (art) artwork.push({ src: art, sizes: "512x512", type: "image/png" });
    try {
      navigator.mediaSession.metadata = new window.MediaMetadata({
        title: title || "Music",
        artist: "Themi",
        album: (box && box.dataset.room) || "",
        artwork: artwork
      });
      if (actions) {
        navigator.mediaSession.setActionHandler("play", actions.play || null);
        navigator.mediaSession.setActionHandler("pause", actions.pause || null);
      }
    } catch (e) { /* an older browser: the page's own buttons still work */ }
  };
})();
