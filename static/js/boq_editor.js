(() => {
  const formset = document.getElementById("boq-items");
  const template = document.getElementById("boq-empty-form");
  const totalForms = document.getElementById("id_boq-TOTAL_FORMS");
  const addRowButton = document.getElementById("boq-add-row");
  const addColumnButton = document.getElementById("boq-add-column");
  const columnNameInput = document.getElementById("boq-new-column-name");
  const searchInput = document.getElementById("boq-row-search");
  const rowCount = document.getElementById("boq-row-count");
  const sheetHead = document.getElementById("boq-sheet-head");
  const sheetBody = document.getElementById("boq-sheet-body");
  const message = document.getElementById("boq-column-message");
  if (!formset || !template || !totalForms || !addRowButton || !sheetHead || !sheetBody) return;

  const coreColumns = [
    {key: "sort_order", label: "#", type: "number", min: "0", width: "boq-col-order"},
    {key: "description", label: "Item / description", type: "text", required: true, width: "boq-col-description"},
    {key: "quantity", label: "Quantity", type: "number", step: "0.001", width: "boq-col-quantity"},
    {key: "unit", label: "Unit", type: "text", maxLength: 60, width: "boq-col-unit"},
    {key: "bidder_response", label: "Bidder response", type: "text", maxLength: 120, width: "boq-col-response"},
  ];
  const knownColumns = new Set();

  function sourceInput(row) {
    return row.querySelector('input[name$="-source_data"]');
  }

  function readSourceData(row) {
    const input = sourceInput(row);
    if (!input || !input.value) return {};
    try {
      const value = JSON.parse(input.value);
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    } catch (_error) {
      return {};
    }
  }

  function writeSourceData(row, data) {
    const input = sourceInput(row);
    if (input) input.value = JSON.stringify(data);
  }

  function coreInput(row, key) {
    return row.querySelector(`[name$="-${key}"]`);
  }

  function fieldForHeader(header) {
    const name = header.toLowerCase();
    if (/\b(qty|quantity|nos|number of units|required quantity)\b/.test(name)) return "quantity";
    if (/\b(unit|uom|unit of measure|measurement)\b/.test(name)) return "unit";
    if (/\b(bidder response|compliance|offered|remarks?|response)\b/.test(name)) return "bidder_response";
    if (/\b(item|description|product|service|material|work|particular|goods?|scope|name)\b/.test(name)
      && !/\b(item\s*(no|number|code|id)|serial|sl\s*(no|number)|specification)\b/.test(name)) return "description";
    return "";
  }

  function preferredHeader(data, fieldName) {
    const candidates = Object.keys(data).filter((header) => fieldForHeader(header) === fieldName);
    if (fieldName === "description") {
      candidates.sort((left, right) => {
        const rank = (header) => [
          !/description|particular|product|service|material|work|name|item/i.test(header),
          /specification/i.test(header),
        ];
        const a = rank(left);
        const b = rank(right);
        return Number(a[0]) - Number(b[0]) || Number(a[1]) - Number(b[1]);
      });
    }
    return candidates[0] || "";
  }

  function displayedExtraColumns() {
    const headers = new Set();
    formset.querySelectorAll("[data-boq-row]").forEach((row) => {
      const data = readSourceData(row);
      Object.keys(data).forEach((header) => headers.add(header));
    });
    return Array.from(headers);
  }

  function activeRows() {
    return Array.from(formset.querySelectorAll("[data-boq-row]")).filter((row) => {
      const deletion = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
      return !row.hidden && !(deletion && deletion.checked);
    });
  }

  function valueFor(row, key) {
    const input = coreInput(row, key);
    return input ? input.value : "";
  }

  function setMessage(text, isError = false) {
    if (!message) return;
    message.textContent = text;
    message.classList.toggle("is-error", isError);
  }

  function updateCoreFromSource(row, header, value) {
    const data = readSourceData(row);
    data[header] = value;
    const coreField = fieldForHeader(header);
    if (coreField && preferredHeader(data, coreField) === header) {
      const input = coreInput(row, coreField);
      if (input) input.value = coreField === "quantity" ? value.replaceAll(",", "").trim() : value;
    }
    writeSourceData(row, data);
  }

  function updateSourceFromCore(row, fieldName, value) {
    const data = readSourceData(row);
    const header = preferredHeader(data, fieldName);
    if (!header) return;
    data[header] = value;
    writeSourceData(row, data);
  }

  function buildColumns(extraHeaders) {
    const fallbackColumns = coreColumns.filter((column) => {
      if (column.key === "sort_order") return false;
      return !extraHeaders.some((header) => fieldForHeader(header) === column.key);
    });
    return [
      {...coreColumns[0], kind: "core"},
      ...extraHeaders.map((header) => ({key: header, label: header, kind: "source", width: "boq-col-extra"})),
      ...fallbackColumns.map((column) => ({...column, kind: "core"})),
      {key: "__actions__", label: "", kind: "actions", width: "boq-col-actions"},
    ];
  }

  function makeHeader(columns) {
    const headRow = document.createElement("tr");
    columns.forEach((column) => {
      const th = document.createElement("th");
      th.className = column.width;
      if (column.kind === "source") {
        const headerInput = document.createElement("input");
        headerInput.type = "text";
        headerInput.className = "boq-sheet-header-input";
        headerInput.value = column.label;
        headerInput.dataset.header = column.key;
        headerInput.maxLength = 120;
        headerInput.setAttribute("aria-label", `Rename ${column.label} column`);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "boq-sheet-remove-column";
        remove.dataset.header = column.key;
        remove.textContent = "×";
        remove.title = `Remove ${column.label} column from the BoQ`;
        th.append(headerInput, remove);
      } else {
        th.textContent = column.label;
      }
      headRow.appendChild(th);
    });
    sheetHead.replaceChildren(headRow);
  }

  function makeCell(row, column, rowNumber) {
    const td = document.createElement("td");
    if (column.kind === "actions") {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "boq-sheet-remove-row";
      remove.textContent = "Remove";
      remove.title = "Remove this BoQ item";
      td.appendChild(remove);
      return td;
    }

    if (column.kind === "core" && column.key === "sort_order") {
      const order = coreInput(row, "sort_order");
      if (order) order.value = String(rowNumber);
      const number = document.createElement("span");
      number.className = "boq-row-number";
      number.textContent = String(rowNumber);
      td.appendChild(number);
      return td;
    }

    const input = document.createElement("input");
    const sourceData = column.kind === "source" ? readSourceData(row) : null;
    const sourceCoreField = column.kind === "source" ? fieldForHeader(column.key) : "";
    const mapsToCore = Boolean(sourceCoreField && preferredHeader(sourceData, sourceCoreField) === column.key);
    input.type = column.kind === "source" ? "text" : (column.type || "text");
    input.className = column.kind === "core" ? "boq-sheet-cell-input" : "boq-sheet-cell-input boq-sheet-extra-input";
    input.dataset.kind = column.kind;
    input.dataset.key = column.key;
    input.value = column.kind === "core"
      ? valueFor(row, column.key)
      : String(sourceData[column.key] ?? (mapsToCore ? valueFor(row, sourceCoreField) : ""));
    input.setAttribute("aria-label", `${column.label || "BoQ"} value`);
    if (column.required || (mapsToCore && sourceCoreField === "description")) input.required = true;
    if (column.min) input.min = column.min;
    if (column.step) input.step = column.step;
    if (column.maxLength) input.maxLength = column.maxLength;
    td.appendChild(input);

    if (column.key === "description" && row.dataset.sourceLabel) {
      const source = document.createElement("small");
      source.className = "boq-sheet-source-label";
      source.textContent = `Source: ${row.dataset.sourceLabel}`;
      td.appendChild(source);
    }
    return td;
  }

  function rowSearchText(row, columns) {
    return columns.map((column) => {
      if (column.kind === "core") return valueFor(row, column.key);
      if (column.kind === "source") return readSourceData(row)[column.key] || "";
      return "";
    }).join(" ").toLowerCase();
  }

  function renderSheet() {
    const extraHeaders = displayedExtraColumns();
    const columns = buildColumns(extraHeaders);
    makeHeader(columns);
    const query = (searchInput?.value || "").trim().toLowerCase();
    const fragment = document.createDocumentFragment();
    const rows = activeRows();
    let visibleCount = 0;

    rows.forEach((row, formIndex) => {
      const tr = document.createElement("tr");
      tr.dataset.formIndex = String(formIndex);
      if (rowSearchText(row, columns).includes(query)) visibleCount += 1;
      else tr.hidden = true;
      columns.forEach((column) => tr.appendChild(makeCell(row, column, formIndex + 1)));
      fragment.appendChild(tr);
    });

    if (!rows.length || !visibleCount) {
      const tr = document.createElement("tr");
      tr.className = query && rows.length ? "boq-sheet-empty boq-sheet-search-empty" : "boq-sheet-empty";
      const td = document.createElement("td");
      td.colSpan = columns.length;
      td.textContent = rows.length ? "No BoQ items match this search." : "No BoQ items yet. Add your first item to start the response.";
      tr.appendChild(td);
      fragment.appendChild(tr);
    }
    sheetBody.replaceChildren(fragment);
    if (rowCount) rowCount.textContent = String(rows.length);
  }

  function applyRowSearch() {
    const query = (searchInput?.value || "").trim().toLowerCase();
    const rows = activeRows();
    const columns = buildColumns(displayedExtraColumns());
    let visible = 0;
    sheetBody.querySelectorAll("tr[data-form-index]").forEach((tableRow) => {
      const row = rows[Number(tableRow.dataset.formIndex)];
      const matches = Boolean(row && rowSearchText(row, columns).includes(query));
      tableRow.hidden = !matches;
      if (matches) visible += 1;
    });
    let empty = sheetBody.querySelector(".boq-sheet-search-empty");
    if (query && rows.length && !visible) {
      if (!empty) {
        empty = document.createElement("tr");
        empty.className = "boq-sheet-empty boq-sheet-search-empty";
        const cell = document.createElement("td");
        cell.colSpan = columns.length;
        cell.textContent = "No BoQ items match this search.";
        empty.appendChild(cell);
        sheetBody.appendChild(empty);
      }
    } else if (empty) {
      empty.remove();
    }
  }

  function refreshKnownColumns() {
    knownColumns.clear();
    displayedExtraColumns().forEach((header) => knownColumns.add(header));
  }

  function renameColumn(oldHeader, newHeader) {
    const name = newHeader.trim();
    if (!name || name.length > 120) {
      setMessage("Column names must contain 1 to 120 characters.", true);
      return false;
    }
    if (name === oldHeader) return true;
    if (fieldForHeader(name)) {
      setMessage("Use the existing core field for description, quantity, unit, or bidder response.", true);
      return false;
    }
    const duplicate = displayedExtraColumns().some((header) =>
      header.toLowerCase() === name.toLowerCase() && header !== oldHeader
    );
    if (duplicate) {
      setMessage(`“${name}” already exists. Choose a different column name.`, true);
      return false;
    }
    formset.querySelectorAll("[data-boq-row]").forEach((row) => {
      const data = readSourceData(row);
      if (!(oldHeader in data)) return;
      const updated = {};
      Object.entries(data).forEach(([header, value]) => {
        updated[header === oldHeader ? name : header] = value;
      });
      writeSourceData(row, updated);
    });
    refreshKnownColumns();
    setMessage(`Renamed “${oldHeader}” to “${name}” across the BoQ.`);
    renderSheet();
    return true;
  }

  function removeColumn(header) {
    const shouldRemove = window.confirm(`Remove the “${header}” column and its values from all BoQ rows?`);
    if (!shouldRemove) return;
    formset.querySelectorAll("[data-boq-row]").forEach((row) => {
      const data = readSourceData(row);
      delete data[header];
      writeSourceData(row, data);
    });
    refreshKnownColumns();
    setMessage(`Removed “${header}” from the BoQ.`);
    renderSheet();
  }

  function removeRow(row) {
    const deletion = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
    if (deletion) deletion.checked = true;
    row.hidden = true;
    renderSheet();
  }

  formset.querySelectorAll("[data-boq-row]").forEach((row) => {
    Object.keys(readSourceData(row)).forEach((header) => knownColumns.add(header));
    row.querySelectorAll('input[name$="-description"]').forEach((input) => { input.required = false; });
  });

  addRowButton.addEventListener("click", () => {
    const index = Number(totalForms.value);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = template.innerHTML.trim().replaceAll("__prefix__", String(index));
    const row = wrapper.firstElementChild;
    const source = {};
    knownColumns.forEach((header) => { source[header] = ""; });
    const input = sourceInput(row);
    if (input) input.value = JSON.stringify(source);
    const order = coreInput(row, "sort_order");
    if (order) order.value = String(activeRows().length + 1);
    row.querySelectorAll('input[name$="-description"]').forEach((input) => { input.required = false; });
    formset.appendChild(row);
    totalForms.value = String(index + 1);
    if (searchInput) searchInput.value = "";
    renderSheet();
    const lastDescription = sheetBody.querySelector(`tr[data-form-index="${activeRows().length - 1}"] input[data-key='description']`);
    if (lastDescription) lastDescription.focus();
  });

  if (addColumnButton && columnNameInput) {
    addColumnButton.addEventListener("click", () => {
      const header = columnNameInput.value.trim();
      if (!header) {
        columnNameInput.focus();
        setMessage("Enter a name for the new column.", true);
        return;
      }
      if (fieldForHeader(header)) {
        setMessage("Description, quantity, unit, and bidder response already have editable columns.", true);
        return;
      }
      if (knownColumns.size >= 100) {
        setMessage("A BoQ can contain up to 100 additional columns.", true);
        return;
      }
      if (Array.from(knownColumns).some((column) => column.toLowerCase() === header.toLowerCase())) {
        setMessage(`“${header}” already exists.`, true);
        return;
      }
      knownColumns.add(header);
      activeRows().forEach((row) => {
        const data = readSourceData(row);
        data[header] = "";
        writeSourceData(row, data);
      });
      columnNameInput.value = "";
      setMessage(`Added “${header}”. Edit its cells in the sheet below.`);
      renderSheet();
    });
  }

  sheetBody.addEventListener("input", (event) => {
    const input = event.target.closest(".boq-sheet-cell-input");
    if (!input) return;
    const tableRow = input.closest("tr");
    const row = activeRows()[Number(tableRow.dataset.formIndex)];
    if (!row) return;
    if (input.dataset.kind === "core") {
      const target = coreInput(row, input.dataset.key);
      if (target) target.value = input.value;
      updateSourceFromCore(row, input.dataset.key, input.value);
    } else {
      updateCoreFromSource(row, input.dataset.key, input.value);
    }
    if (searchInput && searchInput.value.trim()) applyRowSearch();
  });

  sheetBody.addEventListener("click", (event) => {
    const remove = event.target.closest(".boq-sheet-remove-row");
    if (!remove) return;
    const tableRow = remove.closest("tr");
    const row = activeRows()[Number(tableRow.dataset.formIndex)];
    if (row) removeRow(row);
  });

  sheetHead.addEventListener("change", (event) => {
    const input = event.target.closest(".boq-sheet-header-input");
    if (!input) return;
    const oldHeader = input.dataset.header;
    const renamed = renameColumn(oldHeader, input.value);
    if (!renamed) input.value = oldHeader;
  });

  sheetHead.addEventListener("click", (event) => {
    const button = event.target.closest(".boq-sheet-remove-column");
    if (button) removeColumn(button.dataset.header);
  });

  searchInput?.addEventListener("input", applyRowSearch);
  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });
  columnNameInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addColumnButton?.click();
    }
  });
  sheetHead.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches(".boq-sheet-header-input")) {
      event.preventDefault();
      event.target.blur();
    }
  });
  sheetBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.target.matches(".boq-sheet-cell-input")) return;
    event.preventDefault();
    let nextRow = event.target.closest("tr").nextElementSibling;
    while (nextRow && (!nextRow.dataset.formIndex || nextRow.hidden)) nextRow = nextRow.nextElementSibling;
    const selector = `.boq-sheet-cell-input[data-key="${event.target.dataset.key}"]`;
    const nextInput = nextRow && nextRow.querySelector(selector);
    if (nextInput) nextInput.focus();
    else event.target.blur();
  });
  renderSheet();
})();
