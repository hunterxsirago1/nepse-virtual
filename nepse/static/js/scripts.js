document.addEventListener("DOMContentLoaded", function() {
  const globalSearch = document.getElementById("global-search");
  
  if (globalSearch) {
    globalSearch.addEventListener("keypress", function(e) {
      if (e.key === "Enter") {
        const query = globalSearch.value.toUpperCase();
        // Redirect to market page with search query
        window.location.href = `/marketmgmt/?query=${query}`;
      }
    });
  }

  // Dashboard specific animations or data fetching can go here
  console.log("NEPSE Dashboard initialized");
});

