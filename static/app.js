const STORAGE_KEY = "styleguru";
const DEFAULTS = {
  personalise: true,
  photoConsent: false,
  profile: { gender: "", size: "", shoe_size: "", budget: "", colours: [], liked: [], disliked: [] },
};
const COLOURS = {
  Black: "#1f1b16", White: "#ffffff", Grey: "#9a9a9a", Blue: "#3b6fd4", "Navy Blue": "#1f2f5c",
  Green: "#3f8f5a", Red: "#c8372d", Maroon: "#7a1f2b", Pink: "#ee8fb0", Purple: "#7d4fb3",
  Yellow: "#f0c63c", Orange: "#e8833a", Brown: "#7b4b2a", Beige: "#dcc9a8",
};

const $ = (id) => document.getElementById(id);
let saved = load();

let history = [];
let pendingPhoto = null;
let busy = false;

function load() {
  const fresh = structuredClone(DEFAULTS);
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    return { ...fresh, ...stored, profile: { ...fresh.profile, ...stored.profile } };
  } catch {
    return fresh;
  }
}

function save() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  renderPrivacy();
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function icon(path) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.innerHTML = path;
  return svg;
}

const rupees = (amount) => "₹" + Number(amount).toLocaleString("en-IN");

function addBubble(role, text, photoUrl) {
  const bubble = el("div", { className: `bubble ${role}` });
  if (photoUrl) bubble.append(el("img", { src: photoUrl, alt: "Your photo" }));
  bubble.append(text);
  $("messages").append(bubble);
  $("messages").scrollTop = $("messages").scrollHeight;
  return bubble;
}

async function send(text) {
  text = text.trim();
  if (busy || (!text && !pendingPhoto)) return;
  busy = true;
  $("send").disabled = true;
  $("starters").hidden = true;

  const photo = pendingPhoto;
  clearPhoto();
  const shownText = text || "Find me something similar to this.";
  addBubble("user", shownText, photo && URL.createObjectURL(photo));
  const typing = el("div", { className: "bubble assistant typing" }, el("i"), el("i"), el("i"));
  $("messages").append(typing);
  $("messages").scrollTop = $("messages").scrollHeight;

  const body = new FormData();
  body.append("message", shownText);
  body.append("history", JSON.stringify(history));
  if (saved.personalise) body.append("profile", JSON.stringify(saved.profile));
  if (photo) body.append("image", photo);

  try {
    const response = await fetch("/api/chat", { method: "POST", body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Something went wrong. Please try again.");

    typing.remove();
    addBubble("assistant", data.reply);
    history.push(
      { role: "user", text: shownText + (photo ? " [the customer attached a photo]" : "") },
      { role: "assistant", text: data.reply, note: data.note },
    );
    if (data.products) {
      $("results-title").textContent = "Picked for you";
      $("results-subtitle").textContent = saved.personalise
        ? "Ranked using your request and your style profile."
        : "Ranked using your request only. Personalisation is off.";
      renderChips(data.filters || {});
      renderProducts(data.products);
    }
  } catch (error) {
    typing.remove();
    addBubble("error", error.message || "Couldn't reach the assistant. Please try again.");
  } finally {
    busy = false;
    $("send").disabled = false;
    $("input").focus();
  }
}

function clearPhoto() {
  pendingPhoto = null;
  $("file").value = "";
  $("attachment").hidden = true;
}


function renderChips(filters) {
  const labels = [
    ...(filters.product_types || []),
    filters.gender && `For ${filters.gender.toLowerCase()}`,
    ...(filters.colours || []).map((colour) => colour[0].toUpperCase() + colour.slice(1)),
    filters.occasion,
    filters.min_price && `Over ${rupees(filters.min_price)}`,
    filters.max_price && `Under ${rupees(filters.max_price)}`,
    filters.size && `Size ${filters.size}`,
    filters.keywords && `"${filters.keywords}"`,
  ].filter(Boolean);

  $("chips").replaceChildren(...labels.map((label) => {
    const remove = el("button", { textContent: "×", title: "Remove this requirement" });
    remove.setAttribute("aria-label", `Remove ${label}`);
    remove.onclick = () => send(`Drop the "${label}" requirement and search again.`);
    return el("span", { className: "chip" }, label, remove);
  }));
}

function renderProducts(products) {
  const grid = $("grid");
  if (!products.length) {
    grid.replaceChildren(el("p", { className: "empty", textContent: "Nothing matched. Try loosening a requirement." }));
    return;
  }
  grid.replaceChildren(...products.map(productCard));
}

function productCard(product, index) {
  const card = el("article", { className: "card" + (product.available ? "" : " sold-out") });
  card.style.animationDelay = `${index * 40}ms`;

  const photo = el("div", { className: "photo" },
    el("img", { src: product.image, alt: product.name, loading: "lazy" }));
  if (!product.available) {
    const size = product.size_checked;
    photo.append(el("span", {
      className: "badge",
      textContent: size && size !== "One Size" ? `Sold out in ${size}` : "Sold out",
    }));
  }

  if (saved.personalise) {
    const liked = saved.profile.liked.includes(product.id);
    const like = el("button", { className: "like" + (liked ? " on" : ""), title: "Like" },
      icon('<path d="M12 20s-7-4.400-7-10a4 4 0 0 1 7-2.600A4 4 0 0 1 19 10c0 5.600-7 10-7 10z"/>'));
    like.setAttribute("aria-label", `Like ${product.name}`);
    like.onclick = () => {
      const likes = saved.profile.liked;
      const at = likes.indexOf(product.id);
      if (at >= 0) likes.splice(at, 1); else likes.push(product.id);
      like.classList.toggle("on", at < 0);
      save();
    };
    const hide = el("button", { title: "Not for me" }, icon('<path d="M6 6l12 12M18 6L6 18"/>'));
    hide.setAttribute("aria-label", `Hide ${product.name}`);
    hide.onclick = () => {
      saved.profile.disliked.push(product.id);
      saved.profile.liked = saved.profile.liked.filter((id) => id !== product.id);
      save();
      card.remove();
    };
    photo.append(el("div", { className: "card-actions" }, like, hide));
  }

  const body = el("div", { className: "card-body" },
    el("div", { className: "card-name", textContent: product.name }),
    el("div", { className: "card-meta", textContent: `${product.colour} · ${product.occasion}` }),
    el("div", { className: "card-price" },
      el("strong", { textContent: rupees(product.price) }),
      el("span", { textContent: `★ ${product.rating}` })),
  );

  const sizes = Object.entries(product.stock);
  if (sizes.length > 1) {
    body.append(el("div", { className: "sizes" }, ...sizes.map(([size, left]) => el("span", {
      textContent: size,
      className: (left ? "" : "out") + (size === product.size_checked ? " mine" : ""),
      title: left ? `${left} in stock` : "Sold out",
    }))));
  }
  if (product.reasons.length) {
    body.append(el("div", { className: "reasons", textContent: "✓ " + product.reasons.join(" · ") }));
  }

  card.append(photo, body);
  return card;
}

async function showFeatured() {
  const gender = saved.personalise ? saved.profile.gender : "";
  const response = await fetch("/api/featured?gender=" + encodeURIComponent(gender));
  renderProducts(await response.json());
}

function renderProfile() {
  const profile = saved.profile;
  $("p-gender").value = profile.gender;
  $("p-size").value = profile.size;
  $("p-shoe").value = profile.shoe_size;
  $("p-budget").value = profile.budget;
  $("profile-off-notice").hidden = saved.personalise;

  $("p-colours").replaceChildren(...Object.entries(COLOURS).map(([name, hex]) => {
    const swatch = el("i");
    swatch.style.background = hex;
    const button = el("button", { type: "button", className: profile.colours.includes(name) ? "on" : "" }, swatch, name);
    button.onclick = () => {
      profile.colours = profile.colours.includes(name)
        ? profile.colours.filter((colour) => colour !== name)
        : [...profile.colours, name];
      save();
      renderProfile();
    };
    return button;
  }));

  $("p-liked").textContent =
    `${profile.liked.length} liked and ${profile.disliked.length} hidden. ` +
    "Tap the heart on a product to see more like it, or the cross to hide it.";
}

function bindProfileField(id, key) {
  $(id).addEventListener("change", () => {
    saved.profile[key] = $(id).value;
    save();
  });
}


function renderPrivacy() {
  $("personalise").checked = saved.personalise;
  $("personalise-dot").classList.toggle("off", !saved.personalise);
  $("personalise-dot").title = `Personalisation is ${saved.personalise ? "on" : "off"}`;
  $("stored-data").textContent = JSON.stringify(saved, null, 2);
}

function openDrawer(id) {
  renderProfile();
  renderPrivacy();
  $(id).hidden = false;
  $("scrim").hidden = false;
}

function closeDrawers() {
  $("profile-drawer").hidden = true;
  $("privacy-drawer").hidden = true;
  $("scrim").hidden = true;
}

$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("input").value;
  $("input").value = "";
  $("input").style.height = "auto";
  send(text);
});

$("input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
});

$("input").addEventListener("input", () => {
  $("input").style.height = "auto";
  $("input").style.height = $("input").scrollHeight + "px";
});

$("starters").addEventListener("click", (event) => {
  if (event.target.tagName === "BUTTON") send(event.target.textContent);
});


$("attach").addEventListener("click", () => {
  if (saved.photoConsent) $("file").click();
  else $("consent").hidden = false;
});
$("consent-no").addEventListener("click", () => { $("consent").hidden = true; });
$("consent-yes").addEventListener("click", () => {
  saved.photoConsent = true;
  save();
  $("consent").hidden = true;
  $("file").click();
});

$("file").addEventListener("change", () => {
  const file = $("file").files[0];
  if (!file) return;
  pendingPhoto = file;
  $("attachment-preview").src = URL.createObjectURL(file);
  $("attachment").hidden = false;
  $("input").focus();
});
$("remove-attachment").addEventListener("click", clearPhoto);

$("open-profile").addEventListener("click", () => openDrawer("profile-drawer"));
$("open-privacy").addEventListener("click", () => openDrawer("privacy-drawer"));
$("scrim").addEventListener("click", closeDrawers);
document.querySelectorAll(".drawer .close").forEach((button) => button.addEventListener("click", closeDrawers));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeDrawers();
    $("consent").hidden = true;
  }
});

bindProfileField("p-gender", "gender");
bindProfileField("p-size", "size");
bindProfileField("p-shoe", "shoe_size");
bindProfileField("p-budget", "budget");

$("personalise").addEventListener("change", () => {
  saved.personalise = $("personalise").checked;
  save();
});

$("delete-data").addEventListener("click", () => {
  if (!confirm("Delete your style profile, likes, photo consent and this chat?")) return;
  localStorage.removeItem(STORAGE_KEY);
  location.reload();
});

renderPrivacy();
addBubble("assistant", "Hi! I'm StyleGuru. Tell me what you're shopping for, or share a photo of something you like, and I'll find matches from our store.");
showFeatured();
