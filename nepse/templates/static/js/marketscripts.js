function fetchTableData() {
  // Make an AJAX request to your Python script or API endpoint
  const xhr = new XMLHttpRequest();
  xhr.open("GET", "app.py", true);
  xhr.onreadystatechange = function () {
    if (xhr.readyState === 4 && xhr.status === 200) {
      const tableData = JSON.parse(xhr.responseText);
      const tableHtml = generateTableHtml(tableData);
      const tableContainer = document.getElementById("table-container");
      tableContainer.innerHTML = tableHtml;
    }
  };
  xhr.send();
}

// Generate the HTML table from the table data
function generateTableHtml(tableData) {
  let html = "<table>";
  html += "<thead><tr>";
  html += "<th>Column 1</th>";
  html += "<th>Column 2</th>";
  html += "<th>Column 3</th>";
  html += "<th>Column 4</th>";
  html += "<th>Column 5</th>";
  html += "<th>Column 6</th>";
  html += "<th>Column 7</th>";
  html += "</tr></thead>";
  html += "<tbody>";

  // Generate table rows
  tableData.forEach(row => {
    html += "<tr>";
    row.forEach(cell => {
      html += `<td>${cell}</td>`;
    });
    html += "</tr>";
  });

  html += "</tbody></table>";
  return html;
}

// Call the fetchTableData function to fetch and display the table data
fetchTableData();