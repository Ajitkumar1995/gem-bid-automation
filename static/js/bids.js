$(function () {
  const $form = $("#upload-form");
  const $message = $("#upload-message");
  const input = document.getElementById("bid-pdf-input");
  const selectedFile = document.getElementById("selected-file-name");
  const dialog = document.getElementById("upload-error-dialog");
  const dialogDescription = document.getElementById("upload-error-description");
  const maxFileSize = 50 * 1024 * 1024;
  let uploadInProgress = false;

  function showUploadError(message) {
    $message.text(message).css("color", "#a33");
    if (!dialog || !dialogDescription) {
      window.alert(`${message}\n\nAccepted format: a valid PDF (.pdf), up to 50 MB.`);
      return;
    }
    dialogDescription.textContent = message;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else window.alert(`${message}\n\nAccepted format: a valid PDF (.pdf), up to 50 MB.`);
  }

  async function validateFile(file) {
    if (!file) return "Choose a GeM bid PDF before uploading.";
    if (!file.name.toLowerCase().endsWith(".pdf")) return "This file does not have a .pdf extension.";
    if (file.size > maxFileSize) return "This PDF is larger than the 50 MB upload limit.";
    if (file.type && !["application/pdf", "application/octet-stream"].includes(file.type)) {
      return "The selected file is reported as a different file type, not a PDF.";
    }
    try {
      const header = await file.slice(0, 5).arrayBuffer();
      const signature = new TextDecoder().decode(header);
      if (signature !== "%PDF-") return "The file contents do not have a PDF signature. It may be another file renamed as .pdf or a damaged PDF.";
    } catch (_error) {
      return "The selected file could not be checked. Please choose the original GeM PDF again.";
    }
    return "";
  }

  input.addEventListener("invalid", function (event) {
    event.preventDefault();
    showUploadError("Choose a GeM bid PDF before uploading.");
  });

  $(input).on("change", async function () {
    const file = this.files && this.files[0];
    selectedFile.textContent = file ? file.name : "Choose a GeM tender PDF";
    if (!file) return;
    const error = await validateFile(file);
    if (error) showUploadError(error);
    else $message.text("").css("color", "");
  });

  $("#upload-error-close").on("click", function () {
    if (dialog && typeof dialog.close === "function") dialog.close();
  });

  $form.on("submit", async function (event) {
    event.preventDefault();
    if (uploadInProgress || $form.data("at-limit") === true || $form.data("at-limit") === "true") return;
    uploadInProgress = true;
    const fileError = await validateFile(input.files && input.files[0]);
    if (fileError) {
      uploadInProgress = false;
      showUploadError(fileError);
      input.focus();
      return;
    }
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
      const fieldErrors = payload.source_pdf;
      const detail = (Array.isArray(fieldErrors) ? fieldErrors.join(" ") : fieldErrors) || payload.message || payload.detail || "Upload failed. Please check that the file is a valid PDF no larger than 50 MB.";
      showUploadError(detail);
    }).always(function () {
      uploadInProgress = false;
      const atLimit = $form.data("at-limit") === true || $form.data("at-limit") === "true";
      $button.prop("disabled", atLimit).text("Upload and process");
    });
  });
});
