document.addEventListener("DOMContentLoaded", function() {
  const searchInput = document.getElementById("search-box");
  const table = document.getElementById("market-table");
  const rows = table.getElementsByTagName("tbody")[0].getElementsByTagName("tr");

  searchInput.addEventListener("keyup", function () {
    const filter = searchInput.value.toUpperCase();

    for (let i = 0; i < rows.length; i++) {
      // Search across Symbol (index 0) and Name (index 1) if available
      const cells = rows[i].getElementsByTagName("td");
      let found = false;
      
      for (let j = 0; j < Math.min(cells.length, 2); j++) {
        const text = cells[j].textContent || cells[j].innerText;
        if (text.toUpperCase().includes(filter)) {
          found = true;
          break;
        }
      }
      
      rows[i].style.display = found ? "" : "none";
    }
  });

  // Handle query parameter from global search
  const urlParams = new URLSearchParams(window.location.search);
  const query = urlParams.get('query');
  if (query) {
    searchInput.value = query;
    searchInput.dispatchEvent(new Event('keyup'));
  }

  // Add a nice fade-in effect to rows
  Array.from(rows).forEach((row, index) => {
    row.style.animation = `fadeIn 0.3s ease forwards ${index * 0.02}s`;
    row.style.opacity = '0';
  });
});
