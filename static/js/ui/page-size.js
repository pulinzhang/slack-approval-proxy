export const DEFAULT_PAGE_SIZE = 20;

export function paintPagination(element, page, totalPages) {
  if (!(element instanceof HTMLElement)) return;
  const buttons = [];
  for (let number = 1; number <= totalPages; number += 1) {
    const current = number === page ? " aria-current=\"page\"" : "";
    buttons.push(`<button type="button" data-page="${number}"${current}>${number}</button>`);
  }
  element.innerHTML = buttons.join("");
}

export function bindPagination(element, onPage) {
  if (!(element instanceof HTMLElement)) return;
  element.onclick = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const page = target.dataset.page;
    if (page) onPage(Number(page));
  };
}
