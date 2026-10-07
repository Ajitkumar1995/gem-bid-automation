document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("document-edit-form");
  const field = document.getElementById("editable-content");
  const frame = document.getElementById("pdf-preview");
  const status = document.getElementById("preview-status");
  const spinner = document.getElementById("preview-spinner");
  const markCanvas = document.getElementById("document-mark-canvas");
  const markContext = markCanvas?.getContext("2d");
  const markFields = {
    signature: {
      x: document.getElementById("document-signature-x"),
      y: document.getElementById("document-signature-y"),
    },
    stamp: {
      x: document.getElementById("document-stamp-x"),
      y: document.getElementById("document-stamp-y"),
    },
  };
  if (!form || !field || !frame) return;
  const previewUrl = window.location.pathname.replace(/edit\/$/, "preview/");
  let timer;
  let activeUrl;
  let controller;
  const renderPreview = async () => {
    if (controller) controller.abort();
    controller = new AbortController();
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
    const payload = new FormData();
    payload.append("editable_content", field.value);
    payload.append("csrfmiddlewaretoken", csrf);
    Object.values(markFields).forEach(({x, y}) => {
      if (x && y) {
        payload.append(x.name, x.value);
        payload.append(y.name, y.value);
      }
    });
    spinner.textContent = "Rendering preview…";
    status.textContent = "Updating PDF preview…";
    try {
      const response = await fetch(previewUrl, {method: "POST", body: payload, credentials: "same-origin", signal: controller.signal});
      if (!response.ok) throw new Error("Preview could not be rendered.");
      const blob = await response.blob();
      if (activeUrl) URL.revokeObjectURL(activeUrl);
      activeUrl = URL.createObjectURL(blob);
      frame.src = activeUrl;
      spinner.textContent = "";
      status.textContent = "Preview is up to date. Save changes to keep them.";
    } catch (error) {
      if (error.name !== "AbortError") {
        spinner.textContent = "";
        status.textContent = error.message;
      }
    }
  };
  field.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(renderPreview, 450);
  });
  const drawMarkPositions = () => {
    if (!markCanvas || !markContext) return;
    markContext.clearRect(0, 0, markCanvas.width, markCanvas.height);
    markContext.fillStyle = "#f8faf9";
    markContext.fillRect(0, 0, markCanvas.width, markCanvas.height);
    markContext.strokeStyle = "#cbd9d5";
    markContext.setLineDash([5, 5]);
    markContext.beginPath();
    markContext.moveTo(markCanvas.width / 2, 0);
    markContext.lineTo(markCanvas.width / 2, markCanvas.height);
    markContext.stroke();
    markContext.setLineDash([]);
    Object.entries(markFields).forEach(([name, {x, y}]) => {
      if (!x || !y) return;
      const positionX = Number(x.value) / 100 * markCanvas.width;
      const positionY = Number(y.value) / 100 * markCanvas.height;
      markContext.fillStyle = name === "signature" ? "#174d43" : "#a1452b";
      markContext.beginPath();
      markContext.arc(positionX, positionY, 10, 0, Math.PI * 2);
      markContext.fill();
      markContext.fillStyle = "#223438";
      markContext.font = "12px sans-serif";
      markContext.fillText(name === "signature" ? "Signature" : "Stamp", positionX + 13, positionY + 4);
      const xOutput = document.getElementById(`document-${name}-x-output`);
      const yOutput = document.getElementById(`document-${name}-y-output`);
      if (xOutput) xOutput.textContent = `${x.value}%`;
      if (yOutput) yOutput.textContent = `${y.value}%`;
    });
  };
  let draggedMark = null;
  const schedulePreview = () => {
    drawMarkPositions();
    clearTimeout(timer);
    timer = setTimeout(renderPreview, 450);
  };
  Object.values(markFields).forEach(({x, y}) => {
    x?.addEventListener("input", schedulePreview);
    y?.addEventListener("input", schedulePreview);
  });
  if (markCanvas && markContext) {
    markCanvas.addEventListener("pointerdown", (event) => {
      const rect = markCanvas.getBoundingClientRect();
      const pointerX = (event.clientX - rect.left) * markCanvas.width / rect.width;
      const pointerY = (event.clientY - rect.top) * markCanvas.height / rect.height;
      let nearestDistance = Infinity;
      Object.entries(markFields).forEach(([name, {x, y}]) => {
        if (!x || !y) return;
        const dx = pointerX - Number(x.value) / 100 * markCanvas.width;
        const dy = pointerY - Number(y.value) / 100 * markCanvas.height;
        const distance = Math.hypot(dx, dy);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          draggedMark = name;
        }
      });
      if (nearestDistance > 36) draggedMark = null;
      if (draggedMark) {
        markCanvas.setPointerCapture(event.pointerId);
        markCanvas.style.cursor = "grabbing";
      }
    });
    markCanvas.addEventListener("pointermove", (event) => {
      if (!draggedMark) return;
      const fields = markFields[draggedMark];
      const rect = markCanvas.getBoundingClientRect();
      const x = Math.max(0, Math.min(100, (event.clientX - rect.left) / rect.width * 100));
      const y = Math.max(0, Math.min(100, (event.clientY - rect.top) / rect.height * 100));
      fields.x.value = Math.round(x);
      fields.y.value = Math.round(y);
      schedulePreview();
    });
    const stopDragging = () => {
      draggedMark = null;
      markCanvas.style.cursor = "grab";
    };
    markCanvas.addEventListener("pointerup", stopDragging);
    markCanvas.addEventListener("pointercancel", stopDragging);
    markCanvas.style.cursor = "grab";
    drawMarkPositions();
  }
  window.addEventListener("focus", renderPreview);
  window.addEventListener("beforeunload", () => { if (activeUrl) URL.revokeObjectURL(activeUrl); });
});
