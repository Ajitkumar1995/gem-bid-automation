$(function () {
  const $form = $("#upload-form");
  const $message = $("#upload-message");
  $form.on("submit", function (event) {
    event.preventDefault();
    if ($form.data("at-limit") === true || $form.data("at-limit") === "true") return;
    const data = new FormData(this);
    const csrf = $("input[name=csrfmiddlewaretoken]").val();
    const uploadUrl = $form.data("upload-url") || "/api/bids/";
    const $button = $form.find("button").prop("disabled", true).text("Uploading…");
    $.ajax({url: uploadUrl, method: "POST", data, processData: false, contentType: false,
      headers: {"X-CSRFToken": csrf}
    }).done(function () {
      $message.text("Upload received. Processing has started.").css("color", "#147254");
      window.setTimeout(function () { window.location.reload(); }, 900);
    }).fail(function (xhr) {
      const payload = xhr.responseJSON || {};
      const detail = payload.message || payload.detail || "Upload failed. Please try again.";
      $message.text(detail).css("color", "#a33");
    }).always(function () {
      const atLimit = $form.data("at-limit") === true || $form.data("at-limit") === "true";
      $button.prop("disabled", atLimit).text("Upload and process");
    });
  });
});
