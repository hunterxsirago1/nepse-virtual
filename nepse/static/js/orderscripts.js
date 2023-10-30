function autocomplete(inp, arr) {
  var currentFocus;

  inp.addEventListener("input", function(e) {
    var a, b, i, val = this.value;

    closeAllLists();
    if (!val) { return false; }
    currentFocus = -1;

    a = document.createElement("DIV");
    a.setAttribute("id", this.id + "autocomplete-list");
    a.setAttribute("class", "autocomplete-items");

    this.parentNode.appendChild(a);

    for (i = 0; i < arr.length; i++) {
      if (arr[i].substr(0, val.length).toUpperCase() == val.toUpperCase()) {
        b = document.createElement("DIV");

        b.innerHTML = "<strong>" + arr[i].substr(0, val.length) + "<span>" + arr[i].substr(val.length) + "</span></strong>";
        b.innerHTML += "<input type='hidden' value='" + arr[i] + "'>";

        b.addEventListener("click", function(e) {
          inp.value = this.getElementsByTagName("input")[0].value;
          closeAllLists();
        });

        a.appendChild(b);
      }
    }
  });

  inp.addEventListener("keydown", function(e) {
    var x = document.getElementById(this.id + "autocomplete-list");
    if (x) x = x.getElementsByTagName("div");

    if (e.keyCode == 40) {
      currentFocus++;
      addActive(x);
    } else if (e.keyCode == 38) {
      currentFocus--;
      addActive(x);
    } else if (e.keyCode == 13) {
      e.preventDefault();
      if (currentFocus > -1) {
        if (x) x[currentFocus].click();
      }
    }
  });

  function addActive(x) {
    if (!x) return false;

    removeActive(x);
    if (currentFocus >= x.length) currentFocus = 0;
    if (currentFocus < 0) currentFocus = (x.length - 1);

    x[currentFocus].classList.add("autocomplete-active");
  }

  function removeActive(x) {
    for (var i = 0; i < x.length; i++) {
      x[i].classList.remove("autocomplete-active");
    }
  }

  function closeAllLists(elmnt) {
    var x = document.getElementsByClassName("autocomplete-items");
    for (var i = 0; i < x.length; i++) {
      if (elmnt != x[i] && elmnt != inp) {
        x[i].parentNode.removeChild(x[i]);
      }
    }
  }

  document.addEventListener("click", function (e) {
    closeAllLists(e.target);
  });
}

var myInput = document.getElementById("myInput");

fetch('/ordermgmt/data')
  .then(response => response.json())
  .then(data => {
    autocomplete(myInput, data);
  })
  .catch(error => {
    console.error('Error fetching data:', error);
  });

document.addEventListener("DOMContentLoaded", function() {
  const symbolInput = document.getElementById("myInput");
  const quantityInput = document.getElementById("quantity-input");
  const priceInput = document.getElementById("price-input");
  const switchInput = document.querySelector(".switch-box input[type='checkbox']");
  const confirmBtn = document.getElementById("confirm-btn");
  const cancelBtn = document.getElementById("cancel-btn");
  const overlay = document.getElementById("confirmation-overlay");
  const confirmCancelBtn = document.getElementById("confirm-cancel");
  const cancelConfirmBtn = document.getElementById("cancel-confirm");

  let symbolsData = null;

  function fetchSymbolsData() {
    return fetch('/ordermgmt/data2')
      .then(response => response.json())
      .then(data => {
        symbolsData = {
          symbols: data.symbols,
          ltps: data.ltps
        };
      })
      .catch(error => {
        console.error('Error fetching data:', error);
      });
  }

  function fetchSymbolData(symbol) {
    return fetch('/ordermgmt/data3')
      .then(response => response.json())
      .then(data => {
        const index = data.symbols.indexOf(symbol.toUpperCase());
        if (index !== -1) {
          const ltp = data.ltps[index];
          const low = data.lows[index];
          const high = data.highs[index];
          const pclose = data.pcloses[index];

          // Update the table with the fetched data
          const ltpRow = document.getElementById("ltp-row");
          const lowRow = document.getElementById("low-row");
          const highRow = document.getElementById("high-row");
          const pcloseRow = document.getElementById("pclose-row");

          ltpRow.textContent = ltp;
          lowRow.textContent = low;
          highRow.textContent = high;
          pcloseRow.textContent = pclose;
        } else {
          // Symbol not found, clear the table
          const ltpRow = document.getElementById("ltp-row");
          const lowRow = document.getElementById("low-row");
          const highRow = document.getElementById("high-row");
          const pcloseRow = document.getElementById("pclose-row");

          ltpRow.textContent = "";
          lowRow.textContent = "";
          highRow.textContent = "";
          pcloseRow.textContent = "";
        }
      })
      .catch(error => {
        console.error('Error fetching symbol data:', error);
      });
  }

  function priceUpdate() {
    const symbol = symbolInput.value.toUpperCase();
    const quantity = parseFloat(quantityInput.value);

    if (!isNaN(quantity)) {
      if (!symbolsData) {
        fetchSymbolsData().then(calculatePrice);
      } else {
        calculatePrice();
      }
      fetchSymbolData(symbol); // Fetch symbol data for the inputted symbol
    } else {
      priceInput.value = "";
    }
  }

  function calculatePrice() {
    const { symbols, ltps } = symbolsData;
    const index = symbols.findIndex(s => s === symbolInput.value.toUpperCase());

    if (index !== -1) {
      const ltp = parseFloat(ltps[index].replace(/,/g, ""));
      const quantity = parseFloat(quantityInput.value);
      const price = ltp * quantity;
      priceInput.value = Number.isFinite(price) ? price.toFixed(2) : "";
    } else {
      priceInput.value = "";
    }
  }

  let debounceTimer;

  function debounce(callback, delay) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(callback, delay);
  }

  function handleInputChange() {
    debounce(fetchSymbolData, 300);
    debounce(fetchSymbolsData, 300);
    debounce(priceUpdate, 300);
  }

  symbolInput.addEventListener("input", function() {
    symbolInput.value = symbolInput.value.toUpperCase();
    handleInputChange();
    fetchSymbolData(symbolInput.value); // Fetch symbol data for the inputted symbol
  });

  quantityInput.addEventListener("input", handleInputChange);

  // Rest of the code...

  function updateConfirmButton() {
    if (switchInput && switchInput.checked) {
      confirmBtn.textContent = "Sell";
      confirmBtn.style.backgroundColor = "red";
    } else {
      confirmBtn.textContent = "Buy";
      confirmBtn.style.backgroundColor = "green";
    }
  }

  if (switchInput) {
    switchInput.addEventListener("change", updateConfirmButton);
  } else {
    console.error("Switch input element not found.");
  }

  confirmBtn.addEventListener("click", function() {
    const isSwitchOn = switchInput.checked;

    if (isSwitchOn) {
      // Sell logic
      console.log("Sell button clicked");
    } else {
      // Buy logic
      console.log("Buy button clicked");
    }
  });

  updateConfirmButton();

  cancelBtn.addEventListener("click", function() {
    overlay.style.display = "flex";
  });

  confirmCancelBtn.addEventListener("click", function() {
    location.reload();
  });

  cancelConfirmBtn.addEventListener("click", function() {
    overlay.style.display = "none";
  });
});

