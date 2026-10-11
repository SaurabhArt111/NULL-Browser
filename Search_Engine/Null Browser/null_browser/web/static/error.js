"use strict";
(function () {
  const p = new URLSearchParams(location.search);
  const notFound = location.host !== "error";
  const kind = notFound ? "net" : (p.get("kind") || "net"), code = notFound ? "ERR_FILE_NOT_FOUND" : (p.get("code") || ""), url = notFound ? location.href : (p.get("u") || ""), desc = p.get("desc") || "";
  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  let host = url; try { host = new URL(url).host || url; } catch (e) {}
  const H = esc(host);
  const T = {
    ERR_NAME_NOT_RESOLVED: ["This site can't be reached", `<b>${H}</b>'s server IP address could not be found.`, ["Check the address for typos", "Check your internet connection", "Check your DNS or proxy settings"]],
    ERR_INTERNET_DISCONNECTED: ["No internet", "You're not connected to the internet.", ["Check your network cables, modem and router", "Reconnect to Wi-Fi", "Check firewall settings"]],
    ERR_CONNECTION_REFUSED: ["This site can't be reached", `<b>${H}</b> refused to connect.`, ["Make sure the server is running", "Check the port number", "Check your firewall"]],
    ERR_CONNECTION_TIMED_OUT: ["This site can't be reached", `<b>${H}</b> took too long to respond.`, ["Check your connection", "Try again later"]],
    ERR_CONNECTION_RESET: ["The connection was reset", `The connection to <b>${H}</b> was interrupted.`, ["Reload the page", "Check your network"]],
    ERR_SSL_PROTOCOL_ERROR: ["Secure connection failed", `<b>${H}</b> sent an invalid response.`, ["Try http:// if you know the site is not secure", "Check your system date and time"]],
    ERR_ADDRESS_UNREACHABLE: ["This site can't be reached", `The address of <b>${H}</b> is unreachable.`, ["Check your network or VPN"]],
    ERR_BLOCKED_BY_CLIENT: ["Blocked", `<b>${H}</b> was blocked by Null Browser.`, ["Turn off the ad blocker for this site from the shield icon"]],
    ERR_FILE_NOT_FOUND: ["File not found", `<b>${esc(url)}</b> could not be found.`, ["Check the path"]],
    ERR_CERT: ["Your connection is not private", `Attackers might be trying to steal your information from <b>${H}</b> (for example passwords, messages or credit cards).`, []],
    ERR_UNSAFE_PORT: ["This port is blocked", `Browsers refuse to connect to port ${esc(((url.match(/:(\d+)/) || [])[1]) || "")} on <b>${esc(host)}</b> because it is commonly used for attacks.`, ["Use a different port (for local servers 3000, 5000, 8000 or 8080 work)"]],
    ERR_EMPTY_RESPONSE: ["No data received", `<b>${esc(host)}</b> sent back no data.`, ["Reload the page", "The server may be overloaded or crashed"]],
    ERR_CONNECTION_CLOSED: ["The connection was closed", `<b>${esc(host)}</b> closed the connection unexpectedly.`, ["Reload the page", "Check your network or VPN"]],
    ERR_TIMED_OUT: ["This site can't be reached", `<b>${esc(host)}</b> took too long to respond.`, ["Check your connection", "Try again later"]],
    ERR_TOO_MANY_REDIRECTS: ["This page isn't working", `<b>${esc(host)}</b> redirected you too many times.`, ["Clear cookies for this site (Settings -> Privacy)", "Try again later"]],
    ERR_NETWORK_CHANGED: ["Your connection was interrupted", "A network change was detected.", ["Reload the page", "Check your network"]],
    ERR_PROXY_CONNECTION_FAILED: ["Proxy server problem", "Null Browser could not connect to the proxy server.", ["Check your proxy settings or VPN", "Check your firewall"]],
    ERR_TUNNEL_CONNECTION_FAILED: ["Unable to connect to the proxy", `The proxy could not reach <b>${esc(host)}</b>.`, ["Check your proxy / VPN settings"]],
    ERR_ACCESS_DENIED: ["Access denied", `You don't have permission to open <b>${esc(url)}</b>.`, ["Check the file or folder permissions"]],
    ERR_INVALID_URL: ["Invalid address", `<b>${esc(url)}</b> is not a valid web address.`, ["Check the address for typos"]],
    ERR_SSL_VERSION_OR_CIPHER_MISMATCH: ["Secure connection failed", `<b>${esc(host)}</b> uses an unsupported security protocol.`, ["Try again later", "The site may need updating"]],
    ERR_NAME_RESOLUTION_FAILED: ["This site can't be reached", `<b>${esc(host)}</b>'s address could not be found.`, ["Check the address", "Check your DNS settings"]],
    CRASHED: ["Aw, Snap!", "Something went wrong while displaying this page.", ["Close other tabs or programs to free up memory", "Reload the page", "Enable Memory Saver in Settings -> Performance"]],
  };
  const key = kind === "cert" ? "ERR_CERT" : kind === "crash" ? "CRASHED" : code;
  const [title, msg, tips] = T[key] || ["This page isn't working", `<b>${H}</b> can't handle this request right now.`, ["Try reloading the page"]];
  document.title = title;
  document.body.innerHTML = "";
  document.body.style.cssText = "display:grid;place-items:center;min-height:100vh;padding:24px";
  const badIcon = kind === "cert" ? "alert" : kind === "crash" ? "bug" : "globe";
  const card = h("div", { style: "max-width:600px;width:100%" },
    h("div", { style: `width:64px;height:64px;border-radius:20px;display:grid;place-items:center;margin-bottom:18px;background:${kind === "cert" ? "color-mix(in srgb,var(--danger) 18%,transparent);color:var(--danger)" : "var(--surface-2);color:var(--muted)"}`, html: icon(badIcon).replace('class="i ', 'style="width:34px;height:34px" class="i ') }),
    h("h1", { style: "font-size:28px;margin:0 0 10px" }, title), h("p", { html: msg, style: "font-size:15px" }));
  if (tips.length) card.append(h("ul", { class: "muted", style: "line-height:1.9" }, tips.map(t => h("li", {}, t))));
  card.append(h("p", { class: "muted", style: "font-size:12px" }, code));
  const row = h("div", { class: "toolbar" });
  if (kind === "cert") {
    card.append(h("p", { class: "muted", style: "font-size:13px" }, desc || "The site's security certificate is not trusted."));
    row.append(h("button", { class: "btn primary", onclick: () => history.length > 1 ? history.back() : (location.href = "null://newtab") }, "Back to safety"),
      h("button", { class: "btn danger", onclick: async () => { if (await confirmDialog("Proceed anyway?", `Proceeding to ${host} is unsafe. Your data could be stolen.`, "Proceed (unsafe)", true)) { await api("error/proceed", { url }); location.href = url; } } }, "Proceed to site (unsafe)"));
  } else {
    row.append(h("button", { class: "btn primary", onclick: () => { location.href = url || "null://newtab"; } }, h("span", { html: icon("refresh", "sm") }), "Reload"),
      h("button", { class: "btn", onclick: () => { location.href = "null://newtab"; } }, "New tab"),
      kind === "crash" ? h("a", { class: "btn", href: "null://logs" }, "View logs") : "");
  }
  card.append(row);
  document.body.append(card);
  addEventListener("online", () => { if (kind === "net" && url) location.href = url; });
})();
