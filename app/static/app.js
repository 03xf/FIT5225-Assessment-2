const state = { user: localStorage.getItem("pacificbio-demo-user") || "demo.researcher", media: [], environment: "development", auth: null };
const statusNode = document.querySelector("#status");

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.classList.toggle("error", isError);
}
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.environment === "production") {
    const token = localStorage.getItem("pacificbio-id-token");
    if (!token) throw new Error("Sign in with Cognito before using the archive.");
    headers.set("Authorization", `Bearer ${token}`);
  } else {
    headers.set("X-Demo-User", state.user);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}
function tagsFromInput(value) {
  const tags = {};
  for (const part of value.split(",").map((item) => item.trim()).filter(Boolean)) {
    const [species, countText] = part.split(":");
    const count = Number(countText || 1);
    if (!species || !Number.isInteger(count) || count < 1) throw new Error("Use species:minimum pairs, for example bos_taurus:1");
    tags[species.trim()] = count;
  }
  if (!Object.keys(tags).length) throw new Error("Enter at least one tag");
  return tags;
}
function render(media) {
  state.media = media;
  const grid = document.querySelector("#media-grid");
  grid.replaceChildren();
  const template = document.querySelector("#media-card-template");
  for (const item of media) {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".media-card");
    card.dataset.id = item.id;
    card.dataset.url = item.source_url;
    const thumbnail = node.querySelector(".thumbnail");
    const previewLink = node.querySelector(".preview-link");
    if (item.thumbnail_url) { thumbnail.src = item.thumbnail_url; previewLink.href = item.source_url; }
    else { thumbnail.remove(); previewLink.textContent = item.media_type === "video" ? "Video processing completed" : "No thumbnail"; previewLink.href = item.source_url; }
    node.querySelector(".filename").textContent = item.original_name;
    node.querySelector(".metadata").textContent = `${item.media_type} | ${item.status.toLowerCase()} | ${item.model_version || "not classified"}`;
    const tags = node.querySelector(".tags");
    Object.entries(item.tags).forEach(([name, detail]) => { const chip = document.createElement("span"); chip.className = "tag"; chip.textContent = `${name} x ${detail.count}`; tags.append(chip); });
    node.querySelector(".source-link").href = item.source_url;
    grid.append(node);
  }
  if (!media.length) grid.innerHTML = "<p>No matching media yet. Upload a wildlife observation to begin.</p>";
}
async function loadMedia(title = "Recent media") { document.querySelector("#result-title").textContent = title; render(await api("/api/media")); }
function selectedUrls() { return [...document.querySelectorAll(".media-select:checked")].map((box) => box.closest(".media-card").dataset.url); }

async function sha256(file) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}
function checksumBase64(hex) {
  const bytes = new Uint8Array(hex.match(/../g).map((value) => Number.parseInt(value, 16)));
  let binary = "";
  bytes.forEach((value) => { binary += String.fromCharCode(value); });
  return btoa(binary);
}
function base64url(bytes) {
  let binary = "";
  new Uint8Array(bytes).forEach((value) => { binary += String.fromCharCode(value); });
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}
async function beginCognitoLogin() {
  if (!state.auth?.domain || !state.auth?.client_id) throw new Error("Cognito Hosted UI is not configured for this deployment.");
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48)));
  localStorage.setItem("pacificbio-pkce-verifier", verifier);
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const params = new URLSearchParams({ response_type:"code", client_id:state.auth.client_id, redirect_uri:window.location.origin + "/", scope:"openid email profile", code_challenge:challenge, code_challenge_method:"S256" });
  window.location.assign(`${state.auth.domain.replace(/\/$/, "")}/oauth2/authorize?${params}`);
}
async function completeCognitoLogin(code) {
  const verifier = localStorage.getItem("pacificbio-pkce-verifier");
  if (!verifier) throw new Error("The sign-in verifier has expired; please sign in again.");
  const response = await fetch(`${state.auth.domain.replace(/\/$/, "")}/oauth2/token`, { method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:new URLSearchParams({ grant_type:"authorization_code", client_id:state.auth.client_id, code, redirect_uri:window.location.origin + "/", code_verifier:verifier }) });
  const payload = await response.json();
  if (!response.ok || !payload.id_token) throw new Error(payload.error_description || "Cognito sign-in failed");
  localStorage.setItem("pacificbio-id-token", payload.id_token);
  localStorage.removeItem("pacificbio-pkce-verifier");
  history.replaceState({}, "", "/");
}
async function cloudUpload(file) {
  const checksum = await sha256(file);
  const session = await api("/api/upload-sessions", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ filename:file.name, content_type:file.type || "application/octet-stream", checksum_sha256:checksum }) });
  if (session.duplicate) return session.existing_media;
  const response = await fetch(session.upload_url, { method:"PUT", headers:{ "Content-Type":file.type || "application/octet-stream", "x-amz-checksum-sha256":checksumBase64(checksum), "x-amz-meta-sha256":checksum }, body:file });
  if (!response.ok) throw new Error(`S3 upload failed (${response.status})`);
  return api(`/api/media/${session.media_id}/complete`, { method:"POST" });
}

document.querySelector("#upload-form").addEventListener("submit", async (event) => { event.preventDefault(); const file = document.querySelector("#upload-file").files[0]; if (!file) return; setStatus(state.environment === "production" ? "Checking checksum and uploading securely…" : "Uploading and processing…"); try { let item; if (state.environment === "production") item = await cloudUpload(file); else { const data = new FormData(); data.append("file", file); item = await api("/api/media/upload", { method:"POST", body:data }); } setStatus(item.status === "READY" ? `Ready: ${item.original_name}` : `Uploaded: ${item.original_name}; cloud processing is running.`); event.target.reset(); await loadMedia(); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#tag-search-form").addEventListener("submit", async (event) => { event.preventDefault(); try { render(await api("/api/search/tags", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({tags: tagsFromInput(document.querySelector("#tag-search").value)}) })); document.querySelector("#result-title").textContent = "Tag search results"; setStatus("Search complete."); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#species-search-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const species = document.querySelector("#species-search").value.trim(); render(await api("/api/search/species", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({species}) })); document.querySelector("#result-title").textContent = `Species: ${species}`; setStatus("Search complete."); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#thumbnail-resolve-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const thumbnail_url = document.querySelector("#thumbnail-url").value.trim(); if (!thumbnail_url) throw new Error("Enter a thumbnail URL"); const result = await api("/api/resolve-thumbnail", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({thumbnail_url})}); setStatus(`Full media URL: ${result.source_url}`); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#query-file-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const file = document.querySelector("#query-file").files[0]; if (!file) throw new Error("Choose an image first"); const data = new FormData(); data.append("file", file); render(await api("/api/search/by-file", {method:"POST",body:data})); document.querySelector("#result-title").textContent = "Matches from temporary query"; setStatus("Temporary query processed; it was not archived."); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#subscribe-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const species = document.querySelector("#subscribe-species").value.trim(); const result = await api("/api/subscriptions", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({species})}); setStatus(result.email_confirmation_pending ? `Subscribed to ${species}; confirm the SNS email to activate alerts.` : `Subscribed to ${species}.`); event.target.reset(); } catch (error) { setStatus(error.message, true); } });
async function bulk(operation) { try { const urls = selectedUrls(); const tags = document.querySelector("#bulk-tags").value.split(",").map((tag) => tag.trim()).filter(Boolean); if (!urls.length || !tags.length) throw new Error("Select media and enter at least one tag"); await api("/api/media/tags", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({urls,tags,operation})}); setStatus(operation ? "Tags added." : "Tags removed."); await loadMedia(); } catch (error) { setStatus(error.message, true); } }
document.querySelector("#add-tags").addEventListener("click", () => bulk(1)); document.querySelector("#remove-tags").addEventListener("click", () => bulk(0));
document.querySelector("#delete-media").addEventListener("click", async () => { try { const urls = selectedUrls(); if (!urls.length) throw new Error("Select one or more media items"); await api("/api/media", {method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({urls})}); setStatus(state.environment === "production" ? "Selected media deleted from cloud storage and the archive." : "Selected media deleted from the local archive."); await loadMedia(); } catch (error) { setStatus(error.message, true); } });
document.querySelector("#switch-user").addEventListener("click", async () => { try { if (state.environment === "production") { if (localStorage.getItem("pacificbio-id-token")) { localStorage.removeItem("pacificbio-id-token"); const logout = new URL(`${state.auth.domain.replace(/\/$/, "")}/logout`); logout.search = new URLSearchParams({ client_id:state.auth.client_id, logout_uri:window.location.origin + "/" }); window.location.assign(logout); } else await beginCognitoLogin(); return; } const next = window.prompt("Demo user identifier", state.user); if (next && /^[A-Za-z0-9._:@-]{1,128}$/.test(next)) { state.user = next; localStorage.setItem("pacificbio-demo-user", next); bootstrap(); } } catch (error) { setStatus(error.message, true); } });
async function bootstrap() { try { const health = await fetch("/api/health").then((response) => response.json()); state.environment = health.environment; if (state.environment === "production") { state.auth = await fetch("/auth/config").then((response) => response.json()); document.querySelector("#mode-notice").textContent = "Production mode: authenticated Cognito session and checksum-validated private cloud storage."; const code = new URLSearchParams(window.location.search).get("code"); if (code) await completeCognitoLogin(code); if (!localStorage.getItem("pacificbio-id-token")) { document.querySelector("#user-name").textContent = "Sign in required"; document.querySelector("#switch-user").textContent = "Sign in"; setStatus("Sign in with Cognito to access your archive."); return; } document.querySelector("#switch-user").textContent = "Sign out"; } const user = await api("/api/me"); document.querySelector("#user-name").textContent = user.email || user.subject; await loadMedia(); } catch (error) { setStatus(error.message, true); } }
bootstrap();
