(() => {
  const themeToggle = document.querySelector("[data-theme-toggle]");
  if (themeToggle) {
    const themeLabel = themeToggle.querySelector("[data-theme-label]");
    const updateThemeControl = (theme) => {
      document.documentElement.dataset.theme = theme;
      const darkMode = theme === "dark";
      themeToggle.setAttribute("aria-pressed", String(darkMode));
      themeToggle.setAttribute("aria-label", `Ativar modo ${darkMode ? "claro" : "escuro"}`);
      themeLabel.textContent = `Modo ${darkMode ? "claro" : "escuro"}`;
    };

    updateThemeControl(document.documentElement.dataset.theme || "light");
    themeToggle.addEventListener("click", () => {
      const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      updateThemeControl(nextTheme);
      try {
        localStorage.setItem("rota-theme", nextTheme);
      } catch (error) {
        console.warn("Não foi possível salvar a preferência de tema.", error);
      }
    });
  }

  const normalizeAmount = (value) => {
    const cleaned = value.trim().replace(/[^\d,.-]/g, "");
    if (cleaned.includes(",")) {
      return cleaned.replace(/\./g, "").replace(",", ".");
    }
    return cleaned;
  };

  const formatAmount = (field) => {
    const normalized = normalizeAmount(field.value);
    if (!normalized) {
      field.value = "";
      return;
    }

    const amount = Number(normalized);
    if (Number.isFinite(amount)) {
      field.value = new Intl.NumberFormat("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(amount);
    }
  };

  const bindMoneyField = (field) => {
    if (field.dataset.moneyBound === "true") {
      return;
    }
    field.dataset.moneyBound = "true";
    if (field.value) {
      formatAmount(field);
    }

    field.addEventListener("focus", () => {
      const normalized = normalizeAmount(field.value);
      field.value = Number(normalized) === 0 ? "" : normalized.replace(".", ",");
      if (field.value) {
        field.select();
      }
    });
    field.addEventListener("blur", () => formatAmount(field));
    field.form.addEventListener("submit", () => {
      field.value = normalizeAmount(field.value);
    });
  };

  document.querySelectorAll("[data-money]").forEach(bindMoneyField);

  // Ao adicionar/remover categoria, leva junto os valores já digitados no planejamento.
  const planningForm = document.querySelector(".planning-form");
  if (planningForm) {
    document.querySelectorAll("[data-keep-planning]").forEach((form) => {
      form.addEventListener("submit", () => {
        planningForm.querySelectorAll("[data-money]").forEach((field) => {
          const hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = field.name;
          hidden.value = normalizeAmount(field.value);
          form.appendChild(hidden);
        });
      });
    });
  }

  document.querySelectorAll("[data-emoji-picker]").forEach((picker) => {
    const input = picker.querySelector('input[name="bandeira"]');
    const toggle = picker.querySelector(".emoji-picker-toggle");
    const panel = picker.querySelector(".emoji-picker-panel");
    const grid = picker.querySelector(".emoji-picker-grid");
    let emojiOptions;

    const populateEmojiOptions = () => {
      if (emojiOptions) {
        return;
      }

      const isEmoji = /[\p{Emoji_Presentation}\p{Extended_Pictographic}]/u;
      const options = new Set();
      for (const [start, end] of [[0x203c, 0x2bff], [0x1f000, 0x1faff]]) {
        for (let codePoint = start; codePoint <= end; codePoint += 1) {
          const emoji = String.fromCodePoint(codePoint);
          if (isEmoji.test(emoji) && !(codePoint >= 0x1f1e6 && codePoint <= 0x1f1ff)) {
            options.add(emoji);
          }
        }
      }
      options.add("©️");
      options.add("®️");
      options.add("™️");
      for (const key of ["#", "*", ..."0123456789"]) {
        options.add(`${key}\ufe0f\u20e3`);
      }
      const countryCodes = "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ "
        + "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO "
        + "FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE "
        + "JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO "
        + "MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW "
        + "PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM "
        + "TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW";
      for (const countryCode of countryCodes.split(" ")) {
        const flag = Array.from(countryCode, (letter) =>
          String.fromCodePoint(0x1f1e6 + letter.charCodeAt(0) - 65)
        ).join("");
        options.add(flag);
      }

      emojiOptions = document.createDocumentFragment();
      for (const emoji of options) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "emoji-picker-option";
        option.textContent = emoji;
        option.setAttribute("role", "option");
        option.setAttribute("aria-label", `Usar emoji ${emoji}`);
        option.addEventListener("click", () => {
          input.value = emoji;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          panel.hidden = true;
          toggle.setAttribute("aria-expanded", "false");
          toggle.focus();
        });
        emojiOptions.append(option);
      }
      grid.append(emojiOptions);
    };

    toggle.addEventListener("click", () => {
      const isOpening = panel.hidden;
      if (isOpening) {
        populateEmojiOptions();
      }
      panel.hidden = !isOpening;
      toggle.setAttribute("aria-expanded", String(isOpening));
    });

    document.addEventListener("click", (event) => {
      if (!picker.contains(event.target)) {
        panel.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
      }
    });
    picker.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !panel.hidden) {
        panel.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });
  });

  document.querySelectorAll("[data-cover-upload]").forEach((form) => {
    const fileInput = form.querySelector('input[type="file"]');
    const saveButton = form.querySelector(".cover-save");
    const preview = form.closest(".trip-cover").querySelector("[data-cover-preview]");
    const previewStatus = form.querySelector("#cover-preview-status");
    const originalBackgroundImage = preview.style.backgroundImage;
    let previewUrl = null;

    const revokePreviewUrl = () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
      }
    };

    fileInput.addEventListener("change", () => {
      revokePreviewUrl();
      const [file] = fileInput.files;
      if (!file) {
        preview.style.backgroundImage = originalBackgroundImage;
        saveButton.hidden = true;
        fileInput.setCustomValidity("");
        previewStatus.textContent = "";
        return;
      }

      const extension = file.name.split(".").pop().toLowerCase();
      const supportedType = ["image/jpeg", "image/png"].includes(file.type)
        || (!file.type && ["jpg", "jpeg", "png"].includes(extension));
      if (!supportedType) {
        preview.style.backgroundImage = originalBackgroundImage;
        saveButton.hidden = true;
        fileInput.setCustomValidity("Selecione uma imagem JPG ou PNG.");
        previewStatus.textContent = "Selecione uma imagem JPG ou PNG para visualizar.";
        return;
      }

      fileInput.setCustomValidity("");
      previewUrl = URL.createObjectURL(file);
      preview.style.backgroundImage = `url("${previewUrl}")`;
      saveButton.hidden = false;
      previewStatus.textContent = "Prévia da nova capa. Salve para confirmar a alteração.";
    });

    window.addEventListener("beforeunload", revokePreviewUrl, { once: true });
  });

  document.querySelectorAll(".trip-actions-menu").forEach((menu) => {
    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target)) {
        menu.open = false;
      }
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        menu.open = false;
        menu.querySelector("summary").focus();
      }
    });
  });

  document.querySelectorAll("[data-payment-breakdown]").forEach((section) => {
    const rows = section.querySelector("[data-payment-rows]");
    const rowTemplate = section.querySelector("template[data-payment-row-template]");
    const addButton = section.querySelector("[data-add-payment-row]");
    const totalOutput = section.querySelector("[data-payment-total]");

    const updatePaymentTotal = () => {
      const total = [...rows.querySelectorAll("[data-payment-amount]")].reduce((sum, field) => {
        const value = Number(normalizeAmount(field.value));
        return Number.isFinite(value) ? sum + value : sum;
      }, 0);
      totalOutput.textContent = new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
      }).format(total);
    };

    const bindPaymentRow = (row) => {
      bindMoneyField(row.querySelector("[data-payment-amount]"));
      row.querySelector("[data-remove-payment-row]").addEventListener("click", () => {
        row.remove();
        updatePaymentTotal();
        rows.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };

    rows.querySelectorAll("[data-payment-row]").forEach(bindPaymentRow);
    rows.addEventListener("input", updatePaymentTotal);
    rows.addEventListener("change", updatePaymentTotal);
    addButton.addEventListener("click", () => {
      const row = rowTemplate.content.firstElementChild.cloneNode(true);
      rows.append(row);
      bindPaymentRow(row);
      updatePaymentTotal();
    });
    updatePaymentTotal();
  });

  document.querySelectorAll("[data-paid-select]").forEach((statusField) => {
    const form = statusField.form;
    const currencyField = form.querySelector("[data-expense-currency]");
    const currencyPrefix = form.querySelector("[data-currency-prefix]");
    const currencyRow = form.querySelector("[data-currency-row]");
    const originalAmount = form.querySelector("[data-original-amount]");
    const expenseDate = form.querySelector('[name="data_gasto"]');
    const paymentMethod = form.querySelector("[data-payment-method]");
    const rateContainer = form.querySelector("[data-rate-field]");
    const rateTitle = form.querySelector("[data-rate-title]");
    const rateField = form.querySelector("[data-exchange-rate]");
    const rateCaption = form.querySelector("[data-rate-caption]");
    const rateMessage = form.querySelector("[data-rate-message]");
    const valueInBRL = form.querySelector("[data-value-in-brl]");
    let quoteRequestId = 0;

    const updateConvertedAmount = () => {
      const original = Number(normalizeAmount(originalAmount.value));
      const rate = currencyField.value === "BRL" ? 1 : Number(normalizeAmount(rateField.value));
      if (!Number.isFinite(original) || !Number.isFinite(rate) || !original || !rate) {
        valueInBRL.textContent = "Informe valor e cotação";
        return;
      }
      valueInBRL.textContent = new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
      }).format(original * rate);
    };

    const fetchHistoricalRate = async () => {
      const requestId = ++quoteRequestId;
      if (currencyField.value === "BRL") {
        return;
      }
      if (!expenseDate.value) {
        rateField.value = "";
        rateMessage.textContent = "Informe a data para buscar a cotação histórica.";
        updateConvertedAmount();
        return;
      }

      rateField.value = "";
      rateMessage.textContent = "Buscando cotação histórica...";
      updateConvertedAmount();
      try {
        const query = new URLSearchParams({ currency: currencyField.value, date: expenseDate.value });
        const response = await fetch(`/api/exchange-rate?${query}`, {
          headers: { Accept: "application/json" },
        });
        const result = await response.json();
        if (requestId !== quoteRequestId) {
          return;
        }
        if (!response.ok) {
          throw new Error(result.error || "Não foi possível buscar a cotação.");
        }
        rateField.value = result.rate;
        const quoteDate = new Date(`${result.date}T00:00:00`);
        const formattedDate = new Intl.DateTimeFormat("pt-BR").format(quoteDate);
        rateMessage.textContent = `Referência de ${formattedDate}; ajuste se o cartão aplicou outra taxa.`;
        updateConvertedAmount();
      } catch (error) {
        if (requestId === quoteRequestId) {
          rateMessage.textContent = `${error.message} Você pode informar a cotação manualmente.`;
        }
      }
    };

    const updateExpenseFields = () => {
      const isPaid = statusField.value === "1";
      const hasDetailedPayments = [...form.querySelectorAll("[data-payment-amount]")]
        .some((field) => Number(normalizeAmount(field.value)) > 0);
      currencyPrefix.textContent = currencyField.value;
      originalAmount.required = true;
      paymentMethod.required = isPaid && !hasDetailedPayments;
      const isForeignCurrency = currencyField.value !== "BRL";
      currencyRow.classList.toggle("brl-only", !isForeignCurrency);
      rateTitle.textContent = `Cotação ${currencyField.value}→BRL`;
      rateCaption.textContent = `1 ${currencyField.value} vale quantos reais?`;
      rateContainer.hidden = !isForeignCurrency;
      rateField.disabled = !isForeignCurrency;
      rateField.required = isForeignCurrency;
      if (!isForeignCurrency) {
        rateField.value = "1";
        rateMessage.textContent = "";
      }
      updateConvertedAmount();
    };

    statusField.addEventListener("change", updateExpenseFields);
    form.querySelector("[data-payment-rows]")?.addEventListener("input", updateExpenseFields);
    currencyField.addEventListener("change", () => {
      updateExpenseFields();
      fetchHistoricalRate();
    });
    expenseDate.addEventListener("change", fetchHistoricalRate);
    originalAmount.addEventListener("input", updateConvertedAmount);
    rateField.addEventListener("input", updateConvertedAmount);
    updateExpenseFields();
    if (rateField.dataset.autoRate === "true" && currencyField.value !== "BRL" && expenseDate.value) {
      fetchHistoricalRate();
    }
  });
})();

(() => {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch((error) => console.warn("Service worker indisponível.", error));
    });
  }
  const more = document.querySelector(".bottom-nav-more");
  if (more) {
    document.addEventListener("click", (event) => {
      if (more.open && !more.contains(event.target)) more.open = false;
    });
  }
})();