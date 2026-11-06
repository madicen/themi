// RC1a: Google's file picker for the family cookbook. The token comes from Google Identity
// Services in this browser (scope drive.file), so the server's own tokens never reach the
// page; a doc picked here can then be opened by Themi through the same Google account.
(function () {
  "use strict";
  var root = document.getElementById("picker");
  if (!root) return;
  var button = document.getElementById("pick");
  var form = document.getElementById("picked");
  var problem = root.querySelector(".problem");

  function load(src) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function ready() {
    return load("https://apis.google.com/js/api.js")
      .then(function () { return load("https://accounts.google.com/gsi/client"); })
      .then(function () { return new Promise(function (resolve) { window.gapi.load("picker", resolve); }); });
  }

  function show(token) {
    var picker = window.google.picker;
    var view = new picker.DocsView(picker.ViewId.DOCUMENTS)
      .setMimeTypes("application/vnd.google-apps.document");
    new picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(token)
      .setDeveloperKey(root.dataset.key)
      .setAppId(root.dataset.app)
      .setCallback(function (data) {
        if (data.action === picker.Action.PICKED && data.docs && data.docs.length) {
          form.elements.doc.value = data.docs[0].id;
          form.submit();
        }
      })
      .build()
      .setVisible(true);
  }

  button.addEventListener("click", function () {
    button.disabled = true;
    problem.hidden = true;
    ready().then(function () {
      var client = window.google.accounts.oauth2.initTokenClient({
        client_id: root.dataset.client,
        scope: "https://www.googleapis.com/auth/drive.file",
        login_hint: root.dataset.address,
        callback: function (response) {
          button.disabled = false;
          if (response && response.access_token) show(response.access_token);
        },
      });
      client.requestAccessToken({ prompt: "" });
    }, function () {
      button.disabled = false;
      problem.hidden = false;
    });
  });
})();
