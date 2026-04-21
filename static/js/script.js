function showToast(message, tone = "info") {
    const container = document.getElementById("toast-container");
    if (!container || !message) {
        return;
    }

    const toast = document.createElement("div");
    toast.className = `shadow-toast shadow-toast--${tone}`;
    toast.textContent = message;
    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("is-visible"));

    setTimeout(() => {
        toast.classList.remove("is-visible");
        setTimeout(() => toast.remove(), 260);
    }, 2600);
}

function readSearchTerms() {
    const element = document.getElementById("search-terms-data");
    if (!element) {
        return [];
    }

    try {
        return JSON.parse(element.textContent);
    } catch (error) {
        console.error("Unable to parse search terms", error);
        return [];
    }
}

function initializeLoader() {
    const loadingOverlay = document.getElementById("loading-overlay");
    if (!loadingOverlay) {
        return;
    }

    const hideOverlay = () => loadingOverlay.classList.add("is-hidden");
    window.setTimeout(hideOverlay, 120);
}

function handleImageFallback(imageElement) {
    if (!imageElement) {
        return;
    }

    const fallbackSource = imageElement.dataset.fallbackSrc;
    const placeholderSource = imageElement.dataset.placeholderSrc;

    if (!imageElement.dataset.fallbackTried && fallbackSource) {
        imageElement.dataset.fallbackTried = "true";
        imageElement.src = fallbackSource;
        return;
    }

    imageElement.onerror = null;
    if (placeholderSource) {
        imageElement.src = placeholderSource;
    }
}

window.handleImageFallback = handleImageFallback;

function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function appendHighlightedSuggestion(button, term, query) {
    if (!query) {
        button.textContent = term;
        return;
    }

    const pattern = new RegExp(`(${escapeRegExp(query)})`, "ig");
    const fragments = term.split(pattern);

    fragments.forEach((fragment) => {
        if (!fragment) {
            return;
        }

        if (fragment.toLowerCase() === query.toLowerCase()) {
            const strong = document.createElement("strong");
            strong.textContent = fragment;
            button.appendChild(strong);
            return;
        }

        button.appendChild(document.createTextNode(fragment));
    });
}

function initializeSearchSuggestions() {
    const terms = readSearchTerms();
    if (!terms.length) {
        return;
    }

    document.querySelectorAll("[data-search-input]").forEach((input) => {
        const wrapper = input.closest(".search-container");
        const suggestionBox = wrapper ? wrapper.querySelector("[data-search-suggestions]") : null;
        let currentFocus = -1;

        if (!wrapper || !suggestionBox) {
            return;
        }

        const renderSuggestions = (query) => {
            const normalizedQuery = query.trim().toLowerCase();
            suggestionBox.innerHTML = "";
            currentFocus = -1;

            if (normalizedQuery.length < 2) {
                suggestionBox.classList.remove("is-visible");
                return;
            }

            const filtered = Array.from(
                new Set(terms.filter((term) => term.toLowerCase().includes(normalizedQuery)))
            )
                .slice(0, 6);

            if (!filtered.length) {
                suggestionBox.classList.remove("is-visible");
                return;
            }

            filtered.forEach((term) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "suggestion-item";
                appendHighlightedSuggestion(button, term, normalizedQuery);
                button.addEventListener("click", () => {
                    input.value = term;
                    suggestionBox.classList.remove("is-visible");
                    if (input.form?.requestSubmit) {
                        input.form.requestSubmit();
                    } else if (input.form) {
                        input.form.submit();
                    }
                });
                suggestionBox.appendChild(button);
            });

            suggestionBox.classList.add("is-visible");
        };

        input.addEventListener("input", (event) => {
            renderSuggestions(event.target.value);
        });

        input.addEventListener("keydown", (event) => {
            const items = Array.from(suggestionBox.querySelectorAll(".suggestion-item"));
            if (!items.length) {
                return;
            }

            if (event.key === "ArrowDown") {
                event.preventDefault();
                currentFocus = currentFocus < items.length - 1 ? currentFocus + 1 : 0;
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                currentFocus = currentFocus > 0 ? currentFocus - 1 : items.length - 1;
            } else if (event.key === "Enter" && currentFocus >= 0) {
                event.preventDefault();
                items[currentFocus].click();
                return;
            } else if (event.key === "Escape") {
                suggestionBox.classList.remove("is-visible");
                return;
            } else {
                return;
            }

            items.forEach((item, index) => item.classList.toggle("is-active", index === currentFocus));
        });

        input.addEventListener("focus", () => {
            if (input.value.trim().length >= 2) {
                renderSuggestions(input.value);
            }
        });

        document.addEventListener("click", (event) => {
            if (!wrapper.contains(event.target)) {
                suggestionBox.classList.remove("is-visible");
            }
        });
    });
}

function initializeNavbarState() {
    const navbar = document.querySelector(".sticky-navbar");
    if (!navbar) {
        return;
    }

    const syncScrolledState = () => {
        navbar.classList.toggle("scrolled", window.scrollY > 24);
    };

    syncScrolledState();
    window.addEventListener("scroll", syncScrolledState);
}

function initializeRevealAnimations() {
    const items = document.querySelectorAll(".reveal-up");
    if (!items.length || !("IntersectionObserver" in window)) {
        items.forEach((item) => item.classList.add("in-view"));
        return;
    }

    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in-view");
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.18 }
    );

    items.forEach((item) => observer.observe(item));
}

function initializePaymentPanels() {
    const paymentInputs = Array.from(document.querySelectorAll('input[name="payment_method"]'));
    const panels = Array.from(document.querySelectorAll("[data-payment-detail]"));
    const checkoutSubmit = document.querySelector(".checkout-form button[type='submit']");
    if (!paymentInputs.length || !panels.length) {
        return;
    }

    const syncPanels = () => {
        const selected = paymentInputs.find((input) => input.checked)?.value;

        panels.forEach((panel) => {
            const isActive = panel.dataset.paymentDetail === selected;
            panel.classList.toggle("is-active", isActive);
        });

        paymentInputs.forEach((input) => {
            const option = input.closest(".payment-option");
            if (option) {
                option.classList.toggle("is-active", input.checked);
            }
        });

        if (checkoutSubmit) {
            checkoutSubmit.textContent = selected === "card" ? "Continue to secure payment" : "Place order";
        }
    };

    paymentInputs.forEach((input) => input.addEventListener("change", syncPanels));
    syncPanels();
}

function interact(productId, triggerButton) {
    return fetch("/interact", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ product_id: productId }),
    })
        .then((response) => {
            if (!response.ok) {
                throw new Error("Interaction request failed");
            }
            return response.json();
        })
        .then((data) => {
            showToast(data.message || "Saved to your list.", "success");
            if (triggerButton) {
                triggerButton.classList.add("is-saved");
            }
            return data;
        })
        .catch((error) => {
            console.error("Error:", error);
            showToast("Unable to save this item right now.", "warning");
            throw error;
        })
        .finally(() => {
            if (triggerButton) {
                triggerButton.disabled = false;
                triggerButton.classList.remove("loading");
            }
        });
}

function initializeSavedItemActions() {
    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-interact-product-id]");
        if (!button || button.disabled) {
            return;
        }

        event.preventDefault();
        const productId = Number(button.dataset.interactProductId);
        if (Number.isNaN(productId)) {
            return;
        }

        button.disabled = true;
        button.classList.add("loading");

        interact(productId, button).catch(() => {
            // Toasts are handled in interact().
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    initializeLoader();
    initializeSearchSuggestions();
    initializeNavbarState();
    initializeRevealAnimations();
    initializePaymentPanels();
    initializeSavedItemActions();
});
