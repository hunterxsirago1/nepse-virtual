// Improved Autocomplete Logic
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
        if (arr[i].toUpperCase().includes(val.toUpperCase())) {
            b = document.createElement("DIV");
            const index = arr[i].toUpperCase().indexOf(val.toUpperCase());
            b.innerHTML = arr[i].substr(0, index) + 
                         "<strong>" + arr[i].substr(index, val.length) + "</strong>" + 
                         arr[i].substr(index + val.length);
            b.innerHTML += "<input type='hidden' value='" + arr[i] + "'>";
            b.addEventListener("click", function(e) {
                inp.value = this.getElementsByTagName("input")[0].value;
                closeAllLists();
                inp.dispatchEvent(new Event('input'));
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
      if (currentFocus > -1 && x) x[currentFocus].click();
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
    for (var i = 0; i < x.length; i++) x[i].classList.remove("autocomplete-active");
  }

  function closeAllLists(elmnt) {
    var x = document.getElementsByClassName("autocomplete-items");
    for (var i = 0; i < x.length; i++) {
      if (elmnt != x[i] && elmnt != inp) x[i].parentNode.removeChild(x[i]);
    }
  }

  document.addEventListener("click", function (e) {
    closeAllLists(e.target);
  });
}

function calculateFees(price, quantity, isSell) {
    const purchaseValue = price * quantity;
    if (purchaseValue === 0) return { commission: 0, sebonFee: 0, dpFee: 0, total: 0 };
    
    const sebonFeePercent = 0.00015;
    const dpFee = 25;
    
    let commission = 0;
    if (purchaseValue <= 50000) commission = Math.max(10, purchaseValue * 0.0036);
    else if (purchaseValue <= 500000) commission = purchaseValue * 0.0033;
    else if (purchaseValue <= 2000000) commission = purchaseValue * 0.0031;
    else if (purchaseValue <= 10000000) commission = purchaseValue * 0.0027;
    else commission = purchaseValue * 0.0024;
    
    const sebonFee = purchaseValue * sebonFeePercent;
    
    let total = 0;
    if (isSell) {
        total = purchaseValue - commission - sebonFee - dpFee;
    } else {
        total = purchaseValue + commission + sebonFee + dpFee;
    }
    
    return {
        commission,
        sebonFee,
        dpFee,
        total
    };
}

document.addEventListener("DOMContentLoaded", function() {
    const symbolInput = document.getElementById("myInput");
    const quantityInput = document.getElementById("quantity-input");
    const priceInput = document.getElementById("price-input");
    const tradeToggle = document.getElementById("trade-type-toggle");
    const confirmBtn = document.getElementById("confirm-btn");
    const cancelBtn = document.getElementById("cancel-btn");
    const overlay = document.getElementById("confirmation-overlay");
    const confirmCancelBtn = document.getElementById("confirm-cancel");
    const cancelConfirmBtn = document.getElementById("cancel-confirm");
    
    const ltpRow = document.getElementById("ltp-row");
    const commissionRow = document.getElementById("commission-row");
    const sebonRow = document.getElementById("sebon-row");
    const dpRow = document.getElementById("dp-row");
    const netAmountRow = document.getElementById("net-amount-row");

    let currentLTP = 0;

    // Fetch symbols for autocomplete
    fetch('/ordermgmt/data')
        .then(res => res.json())
        .then(data => autocomplete(symbolInput, data));

    function updatePrice() {
        const symbol = symbolInput.value.toUpperCase();
        const qty = parseFloat(quantityInput.value) || 0;
        const isSell = tradeToggle.checked;

        if (symbol) {
            fetch('/ordermgmt/data3')
                .then(res => res.json())
                .then(data => {
                    const idx = data.symbols.indexOf(symbol);
                    if (idx !== -1) {
                        currentLTP = parseFloat(data.ltps[idx].replace(/,/g, ''));
                        ltpRow.innerText = data.ltps[idx];
                        document.getElementById("pclose-row").innerText = data.pcloses[idx];
                        
                        const fees = calculateFees(currentLTP, qty, isSell);
                        
                        commissionRow.innerText = "रु. " + fees.commission.toLocaleString(undefined, {minimumFractionDigits: 2});
                        sebonRow.innerText = "रु. " + fees.sebonFee.toLocaleString(undefined, {minimumFractionDigits: 2});
                        dpRow.innerText = "रु. " + fees.dpFee.toLocaleString(undefined, {minimumFractionDigits: 2});
                        netAmountRow.innerText = "रु. " + fees.total.toLocaleString(undefined, {minimumFractionDigits: 2});
                        
                        priceInput.value = "रु. " + fees.total.toLocaleString(undefined, {minimumFractionDigits: 2});
                    }
                });
        }
    }

    symbolInput.addEventListener("input", updatePrice);
    quantityInput.addEventListener("input", updatePrice);
    tradeToggle.addEventListener("change", updatePrice);

    tradeToggle.addEventListener("change", function() {
        if (this.checked) {
            confirmBtn.innerText = "EXECUTE SELL";
            confirmBtn.className = "sell";
            this.nextElementSibling.style.backgroundColor = "var(--error-color)";
        } else {
            confirmBtn.innerText = "EXECUTE BUY";
            confirmBtn.className = "buy";
            this.nextElementSibling.style.backgroundColor = "var(--success-color)";
        }
    });

    confirmBtn.addEventListener("click", function() {
        const type = tradeToggle.checked ? 'SELL' : 'BUY';
        const symbol = symbolInput.value.toUpperCase();
        const qty = parseInt(quantityInput.value);
        
        if (!symbol || !qty || qty <= 0) {
            alert("Please provide valid Symbol and Quantity");
            return;
        }

        if (currentLTP <= 0) {
            alert("Waiting for market data...");
            return;
        }

        confirmBtn.disabled = true;
        confirmBtn.innerText = "PROCESSING...";

        fetch('/trade/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol: symbol,
                price: currentLTP,
                quantity: qty,
                type: type
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                alert(data.message);
                location.reload();
            } else {
                alert("Error: " + data.message);
                confirmBtn.disabled = false;
                confirmBtn.innerText = type === 'SELL' ? "EXECUTE SELL" : "EXECUTE BUY";
            }
        })
        .catch(err => {
            alert("Network Error: " + err);
            confirmBtn.disabled = false;
            confirmBtn.innerText = type === 'SELL' ? "EXECUTE SELL" : "EXECUTE BUY";
        });
    });

    cancelBtn.addEventListener("click", () => overlay.style.display = "flex");
    confirmCancelBtn.addEventListener("click", () => location.reload());
    cancelConfirmBtn.addEventListener("click", () => overlay.style.display = "none");
});
