(() => {
  const canvas = document.getElementById("signature-canvas");
  const input = document.getElementById("id_signature_image");
  const rotation = document.getElementById("id_signature_rotation");
  const scale = document.getElementById("id_signature_scale");
  const ink = document.getElementById("id_signature_style");
  const stampInput = document.getElementById("id_stamp_image");
  const clearStamp = document.getElementById("id_clear_stamp");
  const stampCanvas = document.getElementById("stamp-canvas");
  const stampRotation = document.getElementById("id_stamp_rotation");
  const stampScale = document.getElementById("id_stamp_scale");
  const signaturePositionX = document.getElementById("id_signature_position_x");
  const signaturePositionY = document.getElementById("id_signature_position_y");
  const stampPositionX = document.getElementById("id_stamp_position_x");
  const stampPositionY = document.getElementById("id_stamp_position_y");
  const companyPositionCanvas = document.getElementById("company-mark-position-canvas");
  const companyPositionContext = companyPositionCanvas?.getContext("2d");
  const positionSliders = {
    signature: {x: document.getElementById("company-signature-x"), y: document.getElementById("company-signature-y")},
    stamp: {x: document.getElementById("company-stamp-x"), y: document.getElementById("company-stamp-y")},
  };
  const stampPreviewBox = document.getElementById("stamp-preview-box");
  if (!canvas || !rotation || !scale || !ink) return;

  const ctx = canvas.getContext("2d");
  let sourceImage = null;
  let isRawUpload = false;
  let signatureMark = null;
  const currentUrl = canvas.dataset.currentImage;
  let stampMark = null;
  let renderStamp = () => {};

  function readPosition(field, fallback) {
    const value = Number(field?.value);
    return Number.isFinite(value) ? value : fallback;
  }

  function syncPositionSliders() {
    [["signature", signaturePositionX, signaturePositionY], ["stamp", stampPositionX, stampPositionY]].forEach(([name, xField, yField]) => {
      const sliders = positionSliders[name];
      [["x", xField], ["y", yField]].forEach(([axis, field]) => {
        if (!field || !sliders[axis]) return;
        sliders[axis].value = field.value;
        const output = document.getElementById(`company-${name}-${axis}-output`);
        if (output) output.textContent = `${field.value}%`;
      });
      const output = document.getElementById(`${name}-position-output`);
      if (output && xField && yField) {
        output.textContent = `PDF position: ${readPosition(xField, 0).toFixed(2)}% from left, ${readPosition(yField, 50).toFixed(2)}% from top.`;
      }
    });
  }

  function drawCompanyPosition() {
    if (!companyPositionCanvas || !companyPositionContext) return;
    const width = companyPositionCanvas.width;
    const height = companyPositionCanvas.height;
    const ctx = companyPositionContext;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#edf3ef";
    ctx.fillRect(0, 0, width, height);
    const page = {x: 30, y: 18, width: width - 60, height: height - 36};
    ctx.fillStyle = "#fff";
    ctx.shadowColor = "#223b3020";
    ctx.shadowBlur = 13;
    ctx.fillRect(page.x, page.y, page.width, page.height);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "#d6e1da";
    ctx.strokeRect(page.x, page.y, page.width, page.height);
    ctx.fillStyle = "#819087";
    ctx.font = "11px sans-serif";
    ctx.fillText("PDF page preview · drag the markers", page.x + 16, page.y + 22);
    ctx.strokeStyle = "#e6ece8";
    for (let row = 0; row < 4; row += 1) {
      ctx.beginPath();
      ctx.moveTo(page.x + 16, page.y + 48 + row * 21);
      ctx.lineTo(page.x + page.width - 16, page.y + 48 + row * 21);
      ctx.stroke();
    }
    [
      ["signature", signaturePositionX, signaturePositionY, "Signature", "#17694e"],
      ["stamp", stampPositionX, stampPositionY, "Stamp", "#b65c3f"],
    ].forEach(([name, xField, yField, label, color]) => {
      const x = page.x + readPosition(xField, name === "stamp" ? 77 : 0) / 100 * page.width;
      const y = page.y + readPosition(yField, 50) / 100 * page.height;
      ctx.fillStyle = `${color}22`;
      ctx.beginPath();
      ctx.arc(x, y, 19, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = "bold 12px sans-serif";
      ctx.fillText(label, Math.min(x + 12, page.x + page.width - 66), y - 12);
    });
  }

  function boundedPosition(canvasElement, x, y, mark) {
    const radians = mark.angle * Math.PI / 180;
    const halfWidth = (Math.abs(Math.cos(radians)) * mark.width + Math.abs(Math.sin(radians)) * mark.height) / 2;
    const halfHeight = (Math.abs(Math.sin(radians)) * mark.width + Math.abs(Math.cos(radians)) * mark.height) / 2;
    const centerX = Math.max(halfWidth, Math.min(canvasElement.width - halfWidth, x));
    const centerY = Math.max(halfHeight, Math.min(canvasElement.height - halfHeight, y));
    return [centerX, centerY];
  }

  function paintMark(context, canvasElement, image, angle, factor, positionX, positionY) {
    const width = image.width * factor;
    const height = image.height * factor;
    const [x, y] = boundedPosition(canvasElement, positionX, positionY, {width, height, angle});
    context.save();
    context.translate(x, y);
    context.rotate(angle * Math.PI / 180);
    context.drawImage(image, -width / 2, -height / 2, width, height);
    context.restore();
  }

  function rotatedSize(width, height, angle) {
    const radians = angle * Math.PI / 180;
    return [
      Math.abs(Math.cos(radians)) * width + Math.abs(Math.sin(radians)) * height,
      Math.abs(Math.sin(radians)) * width + Math.abs(Math.cos(radians)) * height,
    ];
  }

  function bindDrag(canvasElement, xField, yField, getMark, render, outputId, fallbackX, fallbackY) {
    if (!xField || !yField) return;
    const output = document.getElementById(outputId);
    const updateOutput = () => {
      if (output) output.textContent = `PDF position: ${readPosition(xField, fallbackX).toFixed(2)}% from left, ${readPosition(yField, fallbackY).toFixed(2)}% from top. Drag to adjust.`;
    };
    let dragging = false;
    canvasElement.style.cursor = "grab";
    canvasElement.addEventListener("pointerdown", (event) => {
      if (!getMark()) return;
      dragging = true;
      canvasElement.setPointerCapture(event.pointerId);
      canvasElement.style.cursor = "grabbing";
    });
    canvasElement.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const rect = canvasElement.getBoundingClientRect();
      const mark = getMark();
      const [x, y] = boundedPosition(
        canvasElement,
        (event.clientX - rect.left) * canvasElement.width / rect.width,
        (event.clientY - rect.top) * canvasElement.height / rect.height,
        mark,
      );
      xField.value = (x / canvasElement.width * 100).toFixed(2);
      yField.value = (y / canvasElement.height * 100).toFixed(2);
      updateOutput();
      render();
      syncPositionSliders();
      drawCompanyPosition();
    });
    const stopDragging = () => {
      dragging = false;
      canvasElement.style.cursor = "grab";
    };
    canvasElement.addEventListener("pointerup", stopDragging);
    canvasElement.addEventListener("pointercancel", stopDragging);
    updateOutput();
  }

  function makeInk(source, rawUpload) {
    const layer = document.createElement("canvas");
    layer.width = source.naturalWidth || source.width;
    layer.height = source.naturalHeight || source.height;
    const layerContext = layer.getContext("2d", {willReadFrequently: true});
    layerContext.drawImage(source, 0, 0);
    const pixels = layerContext.getImageData(0, 0, layer.width, layer.height);
    const data = pixels.data;
    let left = layer.width, top = layer.height, right = 0, bottom = 0;
    const color = ink.value === "black_ink" ? [20, 20, 24] : [12, 35, 170];
    for (let i = 0; i < data.length; i += 4) {
      const oldAlpha = data[i + 3];
      let alpha = oldAlpha;
      if (rawUpload) {
        const blue = data[i + 2] - Math.max(data[i], data[i + 1]);
        alpha = Math.max(0, Math.min(255, (blue - 10) * 4 * oldAlpha / 255));
      }
      if (alpha < 18) alpha = 0;
      data[i] = color[0]; data[i + 1] = color[1]; data[i + 2] = color[2]; data[i + 3] = alpha;
      if (alpha > 18) {
        const x = (i / 4) % layer.width;
        const y = Math.floor(i / 4 / layer.width);
        left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y);
      }
    }
    if (right <= left || bottom <= top) return null;
    layerContext.putImageData(pixels, 0, 0);
    const pad = 8;
    const x = Math.max(0, left - pad), y = Math.max(0, top - pad);
    const width = Math.min(layer.width - x, right - left + pad * 2);
    const height = Math.min(layer.height - y, bottom - top + pad * 2);
    const cropped = document.createElement("canvas");
    cropped.width = width; cropped.height = height;
    cropped.getContext("2d").drawImage(layer, x, y, width, height, 0, 0, width, height);
    return cropped;
  }

  function render() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#415256"; ctx.font = "14px sans-serif";
    ctx.fillText("Stamp and seal:", canvas.width * 0.58, 50);
    ctx.fillText("Signature:", 10, canvas.height * 0.49);
    document.getElementById("rotation-output").textContent = `${rotation.value}°`;
    document.getElementById("scale-output").textContent = `${Number(scale.value).toFixed(2)}×`;
    const positionX = readPosition(signaturePositionX, 0) / 100 * canvas.width;
    const positionY = readPosition(signaturePositionY, 50) / 100 * canvas.height;
    if (!sourceImage) {
      signatureMark = null;
      ctx.fillStyle = "#647579"; ctx.font = "16px sans-serif";
      ctx.fillText("Upload a signature image to preview", 24, 45);
      drawCompanyPosition();
      return;
    }
    const mark = makeInk(sourceImage, isRawUpload);
    if (!mark) {
      signatureMark = null;
      drawCompanyPosition();
      return;
    }
    const frameScale = Math.max(Number(scale.value), Number(stampScale?.value || 1), 1);
    const [rotatedWidth, rotatedHeight] = rotatedSize(mark.width, mark.height, Number(rotation.value));
    const fit = Math.min(canvas.width * (38 / 56) / rotatedWidth, canvas.height * (30 / 30) / rotatedHeight, 1)
      * Number(scale.value) / frameScale;
    signatureMark = {image: mark, angle: Number(rotation.value), factor: fit, width: mark.width * fit, height: mark.height * fit};
    paintMark(ctx, canvas, mark, signatureMark.angle, fit, positionX, positionY);
    drawCompanyPosition();
  }

  function loadImage(src, rawUpload) {
    const image = new Image();
    image.onload = () => { sourceImage = image; isRawUpload = rawUpload; render(); };
    image.onerror = () => { sourceImage = null; render(); };
    image.src = src;
  }

  function previewUrl(src) {
    const url = new URL(src, window.location.href);
    url.searchParams.set("preview", Date.now().toString());
    return url.toString();
  }

  if (stampCanvas && stampRotation && stampScale) {
    const stampContext = stampCanvas.getContext("2d");
    let stampImage = null;
    renderStamp = function renderStamp() {
      stampContext.clearRect(0, 0, stampCanvas.width, stampCanvas.height);
      stampContext.fillStyle = "#fff";
      stampContext.fillRect(0, 0, stampCanvas.width, stampCanvas.height);
      document.getElementById("stamp-rotation-output").textContent = `${stampRotation.value}°`;
      document.getElementById("stamp-scale-output").textContent = `${Number(stampScale.value).toFixed(2)}×`;
      if (!stampImage) {
        stampMark = null;
        drawCompanyPosition();
        return;
      }
      const width = stampImage.naturalWidth || stampImage.width;
      const height = stampImage.naturalHeight || stampImage.height;
      const angle = Number(stampRotation.value);
      const [rotatedWidth, rotatedHeight] = rotatedSize(width, height, angle);
      const frameScale = Math.max(Number(scale.value), Number(stampScale.value), 1);
      const fit = Math.min(stampCanvas.width * (26 / 56) / rotatedWidth, stampCanvas.height * (20 / 30) / rotatedHeight, 1)
        * Number(stampScale.value) / frameScale;
      stampMark = {
        image: stampImage,
        angle,
        factor: fit,
        width: width * fit,
        height: height * fit,
      };
      paintMark(
        stampContext,
        stampCanvas,
        stampImage,
        stampMark.angle,
        fit,
        readPosition(stampPositionX, 77) / 100 * stampCanvas.width,
        readPosition(stampPositionY, 50) / 100 * stampCanvas.height,
      );
      drawCompanyPosition();
    };
    function loadStamp(src) {
      const image = new Image();
      image.onload = () => { stampImage = image; renderStamp(); };
      image.onerror = () => { stampImage = null; renderStamp(); };
      image.src = src;
    }
    if (stampCanvas.dataset.currentImage) loadStamp(previewUrl(stampCanvas.dataset.currentImage));
    else renderStamp();
    [stampRotation, stampScale].forEach((control) => control.addEventListener("input", renderStamp));
    [[positionSliders.stamp.x, stampPositionX], [positionSliders.stamp.y, stampPositionY]].forEach(([slider, field]) => {
      slider?.addEventListener("input", () => {
        if (field) field.value = slider.value;
        syncPositionSliders();
        renderStamp();
      });
    });
    bindDrag(stampCanvas, stampPositionX, stampPositionY, () => stampMark, renderStamp, "stamp-position-output", 77, 50);
    stampInput?.addEventListener("change", () => {
      const file = stampInput.files?.[0];
      if (!file) {
        if (stampCanvas.dataset.currentImage) loadStamp(previewUrl(stampCanvas.dataset.currentImage));
        else { stampImage = null; renderStamp(); }
        if (stampPreviewBox && !stampCanvas.dataset.currentImage) stampPreviewBox.hidden = true;
        return;
      }
      if (stampPreviewBox) stampPreviewBox.hidden = false;
      loadStamp(URL.createObjectURL(file));
    });
    clearStamp?.addEventListener("change", () => {
      if (clearStamp.checked) {
        stampImage = null;
        renderStamp();
        if (stampPreviewBox) stampPreviewBox.hidden = true;
      }
    });
  }

  if (currentUrl) loadImage(previewUrl(currentUrl), false);
  else render();
  input?.addEventListener("change", () => {
    const file = input.files?.[0];
    if (!file) {
      if (currentUrl) loadImage(previewUrl(currentUrl), false);
      else { sourceImage = null; render(); }
      return;
    }
    loadImage(URL.createObjectURL(file), true);
  });
  [rotation, scale, ink].forEach((control) => control.addEventListener("input", render));
  [[positionSliders.signature.x, signaturePositionX], [positionSliders.signature.y, signaturePositionY]].forEach(([slider, field]) => {
    slider?.addEventListener("input", () => {
      if (field) field.value = slider.value;
      syncPositionSliders();
      render();
    });
  });
  bindDrag(canvas, signaturePositionX, signaturePositionY, () => signatureMark, render, "signature-position-output", 0, 50);

  if (companyPositionCanvas && companyPositionContext) {
    let draggedPosition = "";
    const positionFields = {
      signature: {x: signaturePositionX, y: signaturePositionY, defaultX: 0, color: "#17694e"},
      stamp: {x: stampPositionX, y: stampPositionY, defaultX: 77, color: "#b65c3f"},
    };
    companyPositionCanvas.addEventListener("pointerdown", (event) => {
      const rect = companyPositionCanvas.getBoundingClientRect();
      const px = (event.clientX - rect.left) * companyPositionCanvas.width / rect.width;
      const py = (event.clientY - rect.top) * companyPositionCanvas.height / rect.height;
      const page = {x: 30, y: 18, width: companyPositionCanvas.width - 60, height: companyPositionCanvas.height - 36};
      let nearest = Infinity;
      Object.entries(positionFields).forEach(([name, fields]) => {
        const x = page.x + readPosition(fields.x, fields.defaultX) / 100 * page.width;
        const y = page.y + readPosition(fields.y, 50) / 100 * page.height;
        const distance = Math.hypot(px - x, py - y);
        if (distance < nearest) {
          nearest = distance;
          draggedPosition = name;
        }
      });
      if (nearest > 34) draggedPosition = "";
      if (draggedPosition) {
        companyPositionCanvas.setPointerCapture(event.pointerId);
        companyPositionCanvas.style.cursor = "grabbing";
      }
    });
    companyPositionCanvas.addEventListener("pointermove", (event) => {
      if (!draggedPosition) return;
      const rect = companyPositionCanvas.getBoundingClientRect();
      const page = {x: 30, y: 18, width: companyPositionCanvas.width - 60, height: companyPositionCanvas.height - 36};
      const px = (event.clientX - rect.left) * companyPositionCanvas.width / rect.width;
      const py = (event.clientY - rect.top) * companyPositionCanvas.height / rect.height;
      const fields = positionFields[draggedPosition];
      fields.x.value = (Math.max(0, Math.min(100, (px - page.x) / page.width * 100))).toFixed(2);
      fields.y.value = (Math.max(0, Math.min(100, (py - page.y) / page.height * 100))).toFixed(2);
      syncPositionSliders();
      if (draggedPosition === "signature") render();
      else renderStamp();
    });
    const stopPositionDrag = () => {
      draggedPosition = "";
      companyPositionCanvas.style.cursor = "grab";
    };
    companyPositionCanvas.addEventListener("pointerup", stopPositionDrag);
    companyPositionCanvas.addEventListener("pointercancel", stopPositionDrag);
    companyPositionCanvas.style.cursor = "grab";
  }
  syncPositionSliders();
  drawCompanyPosition();

})();
