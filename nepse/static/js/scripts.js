// Example data fetched from an API
const watchlistData = [
  { symbol: "ABC", ltp: 100.00, high: 105.00, low: 95.00, open: 98.00, close: 102.00, change: "+2.00" },
  { symbol: "XYZ", ltp: 50.00, high: 55.00, low: 45.00, open: 48.00, close: 52.00, change: "-1.50" },
  // Add more data as needed
];

// Function to populate the table dynamically
function populateTable() {
  const tableBody = document.getElementById("watchlist-body");

  // Clear existing table rows
  tableBody.innerHTML = "";

  // Loop through the watchlist data and create table rows
  watchlistData.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.symbol}</td>
      <td>${item.ltp}</td>
      <td>${item.high}</td>
      <td>${item.low}</td>
      <td>${item.open}</td>
      <td>${item.close}</td>
      <td>${item.change}</td>
    `;
    tableBody.appendChild(row);
  });
}

// Call the populateTable function to initially populate the table
populateTable();


// Example values for DP Holdings
let dpValue = 5000;
let dpShares = 100;

