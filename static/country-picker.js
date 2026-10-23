(() => {
  document.querySelectorAll("[data-country-picker]").forEach((picker) => {
    const input = picker.querySelector("#trip-country-search");
    const codeInput = picker.querySelector('input[name="bandeira"]');
    const panel = picker.querySelector(".country-picker-panel");
    const flagPreview = picker.querySelector(".country-search-flag");
    const clearButton = picker.querySelector(".country-clear");
    const errorMessage = picker.querySelector(".country-selection-error");
    const form = picker.closest("form");
    const countries = JSON.parse(document.querySelector("#country-list").textContent);
    const flagsBase = picker.dataset.flagsBase;
    let filteredCountries = [];
    let activeIndex = -1;

    const normalizeSearch = (value) => value
      .normalize("NFD")
      .replace(/\p{Diacritic}/gu, "")
      .toLocaleLowerCase("pt-BR")
      .trim();

    const closeOptions = () => {
      panel.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    };

    const selectCountry = (country) => {
      codeInput.value = country.code;
      input.value = country.name;
      flagPreview.src = `${flagsBase}${country.code.toLowerCase()}.svg`;
      flagPreview.hidden = false;
      clearButton.hidden = false;
      input.setCustomValidity("");
      errorMessage.textContent = "";
      closeOptions();
    };

    const setActiveOption = (index) => {
      const options = panel.querySelectorAll(".country-option");
      if (!options.length) {
        return;
      }
      activeIndex = (index + options.length) % options.length;
      options.forEach((option, optionIndex) => {
        option.classList.toggle("active", optionIndex === activeIndex);
      });
      input.setAttribute("aria-activedescendant", options[activeIndex].id);
      options[activeIndex].scrollIntoView({ block: "nearest" });
    };

    const renderOptions = () => {
      const query = normalizeSearch(input.value);
      filteredCountries = countries
        .filter((country) => (
          normalizeSearch(country.name).includes(query)
          || country.code.toLowerCase().includes(query)
        ))
        .slice(0, 60);
      panel.replaceChildren();
      activeIndex = -1;

      if (!filteredCountries.length) {
        const emptyMessage = document.createElement("p");
        emptyMessage.className = "country-no-results";
        emptyMessage.textContent = "Nenhum país encontrado.";
        panel.append(emptyMessage);
      }

      filteredCountries.forEach((country, index) => {
        const option = document.createElement("button");
        option.type = "button";
        option.id = `trip-country-option-${country.code}`;
        option.className = "country-option";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", String(country.code === codeInput.value));
        option.innerHTML = `<img alt="" aria-hidden="true" src="${flagsBase}${country.code.toLowerCase()}.svg"><span></span><small></small>`;
        option.querySelector("span").textContent = country.name;
        option.querySelector("small").textContent = country.code;
        option.addEventListener("click", () => selectCountry(country));
        option.addEventListener("mousemove", () => setActiveOption(index));
        panel.append(option);
      });
    };

    const openOptions = () => {
      renderOptions();
      panel.hidden = false;
      input.setAttribute("aria-expanded", "true");
    };

    input.addEventListener("focus", openOptions);
    input.addEventListener("input", () => {
      codeInput.value = "";
      flagPreview.hidden = true;
      clearButton.hidden = !input.value;
      input.setCustomValidity("");
      errorMessage.textContent = "";
      openOptions();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" && !panel.hidden) {
        event.preventDefault();
        setActiveOption(activeIndex + 1);
      } else if (event.key === "ArrowUp" && !panel.hidden) {
        event.preventDefault();
        setActiveOption(activeIndex <= 0 ? filteredCountries.length - 1 : activeIndex - 1);
      } else if (event.key === "Enter" && !panel.hidden && filteredCountries.length) {
        event.preventDefault();
        selectCountry(filteredCountries[activeIndex < 0 ? 0 : activeIndex]);
      } else if (event.key === "Escape") {
        closeOptions();
      }
    });
    clearButton.addEventListener("click", () => {
      codeInput.value = "";
      input.value = "";
      flagPreview.hidden = true;
      clearButton.hidden = true;
      input.setCustomValidity("");
      errorMessage.textContent = "";
      closeOptions();
      input.focus();
    });
    form.addEventListener("submit", (event) => {
      if (input.value.trim() && !codeInput.value) {
        const message = "Escolha um país na lista ou limpe a pesquisa.";
        input.setCustomValidity(message);
        errorMessage.textContent = message;
        event.preventDefault();
        input.reportValidity();
      }
    });
    document.addEventListener("click", (event) => {
      if (!picker.contains(event.target)) {
        closeOptions();
      }
    });
  });
})();
