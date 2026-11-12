export function auditTemplate() {
  return `
    <form id="auditForm" class="filters">
      <input id="auditRequestId" name="request_id" placeholder="request_id" />
      <button type="submit">Search</button>
    </form>
    <div id="auditResult"></div>
  `;
}
