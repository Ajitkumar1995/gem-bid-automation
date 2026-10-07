(() => {
  const rows = document.getElementById("boq-items");
  const template = document.getElementById("boq-empty-form");
  const totalForms = document.getElementById("id_boq-TOTAL_FORMS");
  const addButton = document.getElementById("boq-add-row");
  if (!rows || !template || !totalForms || !addButton) return;

  addButton.addEventListener("click", () => {
    const index = Number(totalForms.value);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = template.innerHTML.trim().replaceAll("__prefix__", String(index));
    rows.appendChild(wrapper.firstElementChild);
    totalForms.value = String(index + 1);
  });

  rows.addEventListener("click", (event) => {
    const button = event.target.closest(".boq-remove");
    if (!button) return;
    const row = button.closest("[data-boq-row]");
    const deletion = row?.querySelector('input[type="checkbox"][name$="-DELETE"]');
    if (deletion) deletion.checked = true;
    if (row) row.hidden = true;
  });
})();
