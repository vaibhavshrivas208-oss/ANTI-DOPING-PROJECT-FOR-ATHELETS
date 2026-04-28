// â”€â”€ Substances Data â”€â”€
const substances = [
  { name: "Pseudoephedrine",      cat: "Stimulants",         status: "orange", label: "In-Competition Only", note: "Threshold: 150 mcg/mL" },
  { name: "Testosterone",         cat: "Anabolic Agents",    status: "red",    label: "Always Prohibited",   note: "â€”" },
  { name: "Salbutamol",           cat: "Stimulants",         status: "orange", label: "In-Competition Only", note: "Threshold: 1000 ng/mL" },
  { name: "Erythropoietin (EPO)", cat: "Peptide Hormones",   status: "red",    label: "Always Prohibited",   note: "â€”" },
  { name: "Insulin",              cat: "Peptide Hormones",   status: "red",    label: "Always Prohibited",   note: "â€”" },
  { name: "Cannabis / THC",       cat: "Cannabinoids",       status: "orange", label: "In-Competition Only", note: "Threshold applies" },
  { name: "Ibuprofen",            cat: "NSAIDs",             status: "green",  label: "Permitted",           note: "â€”" },
  { name: "Caffeine",             cat: "Monitoring Program", status: "green",  label: "Permitted",           note: "Monitored" },
];

// â”€â”€ Navigate Between Pages â”€â”€
function go(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (id === 'substances') renderTable();
}

// â”€â”€ Render Substances Table â”€â”€
function renderTable(query = '') {
  const filtered = substances.filter(s =>
    s.name.toLowerCase().includes(query.toLowerCase()) ||
    s.cat.toLowerCase().includes(query.toLowerCase())
  );

  const tbody = document.getElementById('tableBody');

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:40px;color:var(--gray);">No results for "${query}"</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(s => `
    <tr>
      <td><strong>${s.name}</strong></td>
      <td style="color:var(--gray)">${s.cat}</td>
      <td><span class="badge ${s.status}">${s.label}</span></td>
      <td style="color:var(--gray);font-size:0.82rem;">${s.note}</td>
    </tr>
  `).join('');
}

// â”€â”€ Filter Table on Search Input â”€â”€
function filterTable() {
  const query = document.getElementById('search').value;
  renderTable(query);
}

// â”€â”€ Set Footer Year â”€â”€
document.getElementById('yr').textContent = 'Â© ' + new Date().getFullYear() + ' CleanSport. All rights reserved.';

// â”€â”€ Initial Table Render â”€â”€
renderTable();