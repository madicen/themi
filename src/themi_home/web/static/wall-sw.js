// The wall's service worker (WL6): the frame keeps its last good screen when Themi can't be
// reached (a Wi-Fi drop, a restart). Only the page itself is kept; its parts refresh from
// the network, and the page marks itself "Updated 7:40 PM" until they come back.
"use strict";
var CACHE = "themi-wall-v1";

self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return;
  var url = new URL(request.url);
  if (url.pathname !== "/wall") return;
  event.respondWith(
    fetch(request).then(function (response) {
      if (response.ok) {
        var copy = response.clone();
        caches.open(CACHE).then(function (cache) { cache.put("/wall", copy); });
      }
      return response;
    }, function () {
      return caches.open(CACHE).then(function (cache) { return cache.match("/wall"); }).then(
        function (kept) { return kept || Response.error(); }
      );
    })
  );
});
