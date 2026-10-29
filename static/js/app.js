document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#ai-search-form");
  const voiceButton = document.querySelector("#voice-search");
  if (voiceButton) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { voiceButton.title = "Voice input is not supported in this browser."; voiceButton.addEventListener("click", () => { const m=document.querySelector("#ai-message"); if(m) m.textContent="Voice input is not supported here. You can type your request instead."; }); }
    else voiceButton.addEventListener("click", () => { const recognition = new SpeechRecognition(); recognition.lang = "en-IN"; recognition.interimResults = false; voiceButton.disabled = true; voiceButton.textContent = "Listening…"; recognition.onresult = (event) => { document.querySelector("#ai-query").value = event.results[0][0].transcript; }; recognition.onerror = () => { const m=document.querySelector("#ai-message"); if(m) m.textContent="Voice input did not work. Please type your request."; }; recognition.onend = () => { voiceButton.disabled = false; voiceButton.textContent = "🎙 Voice"; }; recognition.start(); });
  }
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.querySelector("#ai-query");
      const message = document.querySelector("#ai-message");
      const results = document.querySelector("#ai-results");
      const button = form.querySelector("button[type='submit']");
      const query = input.value.trim();
      if (!query) return;
      button.disabled = true;
      button.textContent = "Searching…";
      message.textContent = "Looking through available listings…";
      results.replaceChildren();
      try {
        const response = await fetch("/api/ai-search", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({query})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Search failed.");
        message.textContent = `${data.message} (${data.mode})`;
        if (!data.resources.length) {
          const empty = document.createElement("p");
          empty.className = "ai-empty";
          empty.textContent = "No matching listings were found. Try a broader description or browse all resources.";
          results.appendChild(empty);
        }
        data.resources.forEach(resource => {
          const card = document.createElement("a");
          card.className = "ai-result-card";
          card.href = resource.url;
          const name = document.createElement("strong");
          name.textContent = resource.name;
          const meta = document.createElement("span");
          meta.textContent = `${resource.category} · ${resource.location}` + (resource.reasons?.length ? ` · ${resource.reasons.join(" · ")}` : "");
          const price = document.createElement("b");
          price.textContent = `₹${Number(resource.price).toLocaleString("en-IN")} / ${resource.price_unit}`;
          card.append(name, meta, price);
          results.appendChild(card);
        });
      } catch (error) {
        message.textContent = error.message || "Search is temporarily unavailable.";
      } finally {
        button.disabled = false;
        button.textContent = "Find matches ↗";
      }
    });
  }
  document.querySelectorAll("[data-confirm]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!window.confirm(button.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll("input[type='datetime-local']").forEach((input) => {
    const min = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    input.min = min;
    input.addEventListener("change", () => {
      const form = input.closest("form");
      const start = form?.querySelector("input[name='start_at']");
      const end = form?.querySelector("input[name='end_at']");
      if (start && end && start.value) end.min = start.value;
    });
  });
});
// Owner listing assistant: uses the Flask endpoint and clearly labels fallback suggestions.
(() => {
  const button = document.getElementById('listing-assist');
  if (!button) return;
  button.addEventListener('click', async () => {
    const description = document.getElementById('listing-description');
    const status = document.getElementById('listing-assist-status');
    const suggestion = document.getElementById('listing-suggestion');
    const name = document.querySelector('[name="name"]')?.value || 'resource';
    const category = document.querySelector('[name="category"]')?.value || 'Other';
    if (!description || description.value.trim().length < 10) {
      status.textContent = 'Add at least a sentence about the resource first.';
      return;
    }
    button.disabled = true;
    status.textContent = 'Preparing a clearer listing…';
    suggestion.hidden = true;
    try {
      const response = await fetch('/api/listing-assistant', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, category, description: description.value})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not create a suggestion.');
      suggestion.textContent = data.suggestion + '\n\nMode: ' + data.mode + '. Review all details before using this text.';
      suggestion.hidden = false;
      const apply = document.createElement('button');
      apply.type = 'button'; apply.className = 'btn btn-small btn-primary'; apply.textContent = 'Use suggestion';
      apply.addEventListener('click', () => { description.value = data.suggestion; description.focus(); });
      suggestion.appendChild(document.createElement('br'));
      suggestion.appendChild(apply);
      status.textContent = 'Suggestion ready. Verify that it contains no invented claims.';
    } catch (error) {
      status.textContent = error.message || 'Assistant unavailable. You can still write the listing manually.';
    } finally { button.disabled = false; }
  });
})();
