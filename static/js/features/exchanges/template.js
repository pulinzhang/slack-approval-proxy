export function exchangesTemplate() {
  return `
    <form id="exchangeFilters" class="filters">
      <input name="request_id" placeholder="request_id" />
      <input name="correlation_id" placeholder="correlation_id" />
      <input name="direction" placeholder="direction" />
      <input name="exchange_status" placeholder="exchange_status" />
      <input name="business_outcome" placeholder="business_outcome" />
      <input name="operation" placeholder="operation" />
      <label><input name="include_operator_reads" type="checkbox" /> include operator reads</label>
      <button type="submit">Search</button>
    </form>
    <div id="exchangeTable"></div>
    <div id="exchangePager" class="pager"></div>
  `;
}
