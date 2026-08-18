const $ = (id) => document.getElementById(id);

const DEFAULT_AVATAR =
    "data:image/svg+xml;charset=UTF-8," +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120">' +
        '<rect width="120" height="120" rx="60" fill="#10b981"/>' +
        '<text x="60" y="75" text-anchor="middle" font-size="55">👤</text>' +
        "</svg>"
    );

let currentChatId = localStorage.getItem("currentChatId") || null;
let currentUser = null;

function getCurrentUser() {
    try {
        const raw = localStorage.getItem("currentUser");
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function setCurrentUser(user) {
    currentUser = user;
    localStorage.setItem("currentUser", JSON.stringify(user));
}

function clearCurrentUser() {
    currentUser = null;
    localStorage.removeItem("currentUser");
    localStorage.removeItem("currentChatId");
    currentChatId = null;
}

function userStoragePrefix() {
    return currentUser ? `user_${currentUser.id}` : "guest";
}

function getProfile() {
    try {
        const key = currentUser ? `medicalProfile_${currentUser.id}` : "medicalProfile";
        return JSON.parse(localStorage.getItem(key) || "{}");
    } catch {
        return {};
    }
}

function saveProfileLocal(profile) {
    const key = currentUser ? `medicalProfile_${currentUser.id}` : "medicalProfile";
    localStorage.setItem(key, JSON.stringify(profile));
}

function getChats() {
    try {
        const key = `${userStoragePrefix()}_chatIndex`;
        return JSON.parse(localStorage.getItem(key) || "[]");
    } catch {
        return [];
    }
}

function saveChats(chats) {
    localStorage.setItem(`${userStoragePrefix()}_chatIndex`, JSON.stringify(chats));
}

function getMessages(chatId) {
    try {
        const key = `${userStoragePrefix()}_messages_${chatId}`;
        return JSON.parse(localStorage.getItem(key) || "[]");
    } catch {
        return [];
    }
}

function saveMessages(chatId, messages) {
    localStorage.setItem(`${userStoragePrefix()}_messages_${chatId}`, JSON.stringify(messages));
}

function escapeHTML(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}

function getTime() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function getDate(dateString) {
    if (!dateString) return "";
    return new Date(dateString).toLocaleDateString([], { month: "short", day: "numeric" });
}

function getAvatar() {
    const profile = getProfile();
    return profile.photo || DEFAULT_AVATAR;
}

function setTheme(theme) {
    const isDark = theme === "dark";
    document.body.classList.toggle("dark", isDark);
    localStorage.setItem("theme", theme);

    if ($("themeIcon")) $("themeIcon").textContent = isDark ? "☀️" : "🌙";
    if ($("themeText")) $("themeText").textContent = isDark ? "Light Mode" : "Dark Mode";
}

function toggleTheme() {
    const dark = document.body.classList.contains("dark");
    setTheme(dark ? "light" : "dark");
}

function updateProfileUI() {
    const profile = getProfile();
    const name = profile.name || currentUser?.name || "Profile";
    if ($("miniName")) $("miniName").textContent = name;
    if ($("accountSummary")) $("accountSummary").textContent = currentUser ? `Signed in as ${currentUser.name}` : "Not signed in";
}

function openSettings() {
    const profile = getProfile();
    if ($("profileName")) $("profileName").value = profile.name || currentUser?.name || "";
    if ($("profileAge")) $("profileAge").value = profile.age || "";
    if ($("profileGender")) $("profileGender").value = profile.gender || "";
    if ($("profileBlood")) $("profileBlood").value = profile.blood_group || "";
    if ($("profileHistory")) $("profileHistory").value = profile.medical_history || "";
    if ($("profileAllergies")) $("profileAllergies").value = profile.allergies || "";
    if ($("profileMedications")) $("profileMedications").value = profile.medications || "";
    if ($("profileDetails")) $("profileDetails").value = profile.additional_details || "";
    if ($("profilePhoto")) $("profilePhoto").src = profile.photo || DEFAULT_AVATAR;
    $("settingsModal").classList.add("open");
}

function closeSettings() {
    $("settingsModal").classList.remove("open");
}

function saveProfileToServer() {
    const profile = {
        name: $("profileName").value.trim(),
        age: $("profileAge").value.trim(),
        gender: $("profileGender").value,
        blood_group: $("profileBlood").value.trim(),
        medical_history: $("profileHistory").value.trim(),
        allergies: $("profileAllergies").value.trim(),
        medications: $("profileMedications").value.trim(),
        additional_details: $("profileDetails").value.trim(),
        photo: $("profilePhoto").src || DEFAULT_AVATAR,
    };

    saveProfileLocal(profile);
    updateProfileUI();

    return fetch("/profile/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile })
    });
}

if ($("themeBtn")) $("themeBtn").onclick = toggleTheme;
if ($("topThemeBtn")) $("topThemeBtn").onclick = toggleTheme;
if ($("topProfileBtn")) $("topProfileBtn").onclick = openSettings;
if ($("closeSettingsBtn")) $("closeSettingsBtn").onclick = closeSettings;
if ($("settingsModal")) $("settingsModal").onclick = (event) => { if (event.target === $("settingsModal")) closeSettings(); };

if ($("saveProfileBtn")) {
    $("saveProfileBtn").onclick = async () => {
        try {
            await saveProfileToServer();
            closeSettings();
        } catch (e) {
            console.error(e);
            alert("Could not save profile.");
        }
    };
}

if ($("photoInput")) {
    $("photoInput").onchange = (event) => {
        const file = event.target.files?.[0];
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {
            alert("Please choose a photo smaller than 2 MB.");
            return;
        }
        const reader = new FileReader();
        reader.onload = () => { $("profilePhoto").src = reader.result; };
        reader.readAsDataURL(file);
    };
}

function showAuthScreen() {
    $("welcomeScreen").classList.remove("hidden");
    $("app").classList.add("hidden");
    if ($("loginForm")) $("loginForm").classList.add("active");
    if ($("signupForm")) $("signupForm").classList.remove("active");
}

function showAppScreen() {
    $("welcomeScreen").classList.add("hidden");
    $("app").classList.remove("hidden");
    setTheme(localStorage.getItem("theme") || "light");
    updateProfileUI();
    ensureChat();
    renderChatList();
    renderMessages(getMessages(currentChatId));
    if (currentChatId) loadBackendHistory(currentChatId);
    $("messageInput")?.focus();
}

async function checkAuth() {
    try {
        const response = await fetch("/auth/me");
        const data = await response.json();
        if (data.logged_in) {
            currentUser = data.user;
            localStorage.setItem("currentUser", JSON.stringify(data.user));
            await loadProfileFromServer();
            showAppScreen();
            return;
        }
        clearCurrentUser();
        showAuthScreen();
    } catch {
        showAuthScreen();
    }
}

async function loadProfileFromServer() {
    if (!currentUser) return;
    try {
        const response = await fetch("/profile/load");
        const data = await response.json();
        if (data.success && data.profile) {
            saveProfileLocal(data.profile);
        }
    } catch (error) {
        console.warn("Profile load failed", error);
    }
}

async function handleAuthSubmit(mode, payload) {
    try {
        const response = await fetch(`/auth/${mode}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            alert(data.error || "Authentication failed.");
            return;
        }
        currentUser = data.user;
        localStorage.setItem("currentUser", JSON.stringify(data.user));
        await loadProfileFromServer();
        showAppScreen();
    } catch (error) {
        console.error(error);
        alert("Authentication failed. Please try again.");
    }
}

if ($("loginForm")) {
    $("loginForm").onsubmit = (event) => {
        event.preventDefault();
        handleAuthSubmit("login", {
            email: $("loginEmail").value.trim(),
            password: $("loginPassword").value
        });
    };
}

if ($("signupForm")) {
    $("signupForm").onsubmit = (event) => {
        event.preventDefault();
        handleAuthSubmit("signup", {
            name: $("signupName").value.trim(),
            email: $("signupEmail").value.trim(),
            password: $("signupPassword").value
        });
    };
}

if ($("logoutBtn") || $("logoutSettingsBtn")) {
    const logoutAction = async () => {
        try {
            await fetch("/auth/logout", { method: "POST" });
        } catch {}
        clearCurrentUser();
        showAuthScreen();
        if ($("loginEmail")) $("loginEmail").value = "";
        if ($("loginPassword")) $("loginPassword").value = "";
        if ($("signupName")) $("signupName").value = "";
        if ($("signupEmail")) $("signupEmail").value = "";
        if ($("signupPassword")) $("signupPassword").value = "";
        closeSettings();
    };
    if ($("logoutBtn")) $("logoutBtn").onclick = logoutAction;
    if ($("logoutSettingsBtn")) $("logoutSettingsBtn").onclick = logoutAction;
}

if (document.querySelector(".auth-tab")) {
    document.querySelectorAll(".auth-tab").forEach((tab) => {
        tab.onclick = () => {
            document.querySelectorAll(".auth-tab").forEach((btn) => btn.classList.toggle("active", btn === tab));
            const mode = tab.dataset.mode;
            const login = $("loginForm");
            const signup = $("signupForm");
            if (mode === "login") {
                login.classList.add("active");
                signup.classList.remove("active");
            } else {
                login.classList.remove("active");
                signup.classList.add("active");
            }
        };
    });
}

function createChat() {
    const id = "chat-" + (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random());
    const chatList = getChats();
    chatList.unshift({ id, title: "New conversation", created_at: new Date().toISOString(), updated_at: new Date().toISOString() });
    saveChats(chatList);
    saveMessages(id, []);
    currentChatId = id;
    localStorage.setItem("currentChatId", id);
    renderChatList();
    renderMessages([]);
    fetch("/new_chat", { method: "POST" }).catch(() => {});
    return id;
}

function ensureChat() {
    if (!currentChatId) {
        createChat();
        return;
    }
    const exists = getChats().some((chat) => chat.id === currentChatId);
    if (!exists) createChat();
}

async function deleteChat(chatId) {
    if (!confirm("Are you sure you want to delete this chat?")) return;
    try {
        const response = await fetch(`/delete_chat/${chatId}`, { method: "POST" });
        if (response.ok) {
            const chats = getChats().filter((c) => c.id !== chatId);
            saveChats(chats);
            if (currentChatId === chatId) {
                currentChatId = null;
                localStorage.removeItem("currentChatId");
                localStorage.removeItem(`${userStoragePrefix()}_messages_${chatId}`);
                renderMessages([]);
            }
            renderChatList();
        }
    } catch (error) {
        console.error("Delete error:", error);
    }
}

function renderChatList() {
    const list = $("chatList");
    if (!list) return;
    list.innerHTML = "";
    const chats = getChats();
    if (!chats.length) {
        list.innerHTML = '<div class="no-chat">No previous chats yet.</div>';
        return;
    }

    chats.forEach((chat) => {
        const item = document.createElement("div");
        item.className = "chat-item " + (chat.id === currentChatId ? "active" : "");
        item.innerHTML = `
            <div class="chat-icon">💬</div>
            <div style="min-width:0;">
                <div class="chat-title">${escapeHTML(chat.title)}</div>
                <div class="chat-date">${getDate(chat.updated_at)}</div>
            </div>
            <button class="delete-chat-btn" title="Delete chat" onclick="event.stopPropagation(); deleteChat('${chat.id}')">✕</button>
        `;

        item.onclick = () => {
            currentChatId = chat.id;
            localStorage.setItem("currentChatId", chat.id);
            renderChatList();
            renderMessages(getMessages(chat.id));
            loadBackendHistory(chat.id);
            if ($("sidebar")) $("sidebar").classList.remove("open");
        };

        list.appendChild(item);
    });
}

function renderMessages(messages) {
    const container = $("messages");
    if (!container) return;
    container.innerHTML = "";
    if (!messages.length) {
        container.innerHTML = `
            <div class="empty">
                <div class="empty-icon">🤖</div>
                <h2>How can I help you?</h2>
                <p>Ask a clinical guideline question. Your saved profile information is already available to the assistant.</p>
            </div>`;
        return;
    }
    messages.forEach((message) => addMessageUI(message.role, message.text, message.time, false));
    scrollToBottom();
}

function addMessageUI(role, text, time = getTime(), scroll = true) {
    const isUser = role === "user";
    const row = document.createElement("div");
    row.className = "message-row " + (isUser ? "user" : "bot");

    const avatar = document.createElement("div");
    avatar.className = "avatar " + (isUser ? "user-avatar" : "bot-avatar");
    if (isUser) {
        const image = document.createElement("img");
        image.src = getAvatar();
        image.alt = "User";
        avatar.appendChild(image);
    } else {
        avatar.textContent = "🤖";
    }

    const wrapper = document.createElement("div");
    wrapper.className = "message-wrap";
    const bubble = document.createElement("div");
    bubble.className = "bubble " + (isUser ? "user-bubble" : "bot-bubble");

    const name = document.createElement("div");
    name.className = "message-name";
    name.textContent = isUser ? "You" : "Guideline Assistant";

    const content = document.createElement("div");
    content.textContent = text;
    bubble.appendChild(name);
    bubble.appendChild(content);

    if (!isUser) {
        const copyButton = document.createElement("button");
        copyButton.className = "copy";
        copyButton.textContent = "📋 Copy";
        copyButton.onclick = async () => {
            try {
                await navigator.clipboard.writeText(text);
                copyButton.textContent = "✓ Copied";
                setTimeout(() => { copyButton.textContent = "📋 Copy"; }, 1200);
            } catch {
                alert("Could not copy the message.");
            }
        };
        bubble.appendChild(copyButton);
    }

    wrapper.appendChild(bubble);
    const timestamp = document.createElement("div");
    timestamp.className = "message-time";
    timestamp.textContent = time || "";
    wrapper.appendChild(timestamp);

    if (isUser) {
        row.appendChild(wrapper);
        row.appendChild(avatar);
    } else {
        row.appendChild(avatar);
        row.appendChild(wrapper);
    }

    $("messages").appendChild(row);
    if (scroll) scrollToBottom();
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        const chatArea = $("chatArea");
        if (chatArea) chatArea.scrollTop = chatArea.scrollHeight;
    });
}

function showTyping() {
    if ($("typingRow")) return;
    const row = document.createElement("div");
    row.id = "typingRow";
    row.className = "typing";
    row.innerHTML = `<div class="avatar bot-avatar">🤖</div><div class="typing-bubble"><div class="dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div></div>`;
    $("messages").appendChild(row);
    scrollToBottom();
}

function hideTyping() {
    const typing = $("typingRow");
    if (typing) typing.remove();
}

function updateChatTitle(message) {
    const chats = getChats();
    const chat = chats.find((item) => item.id === currentChatId);
    if (!chat) return;
    if (chat.title === "New conversation") {
        chat.title = message.length > 42 ? message.slice(0, 42) + "…" : message;
    }
    chat.updated_at = new Date().toISOString();
    saveChats(chats);
    renderChatList();
}

async function sendMessage(message) {
    ensureChat();
    const messages = getMessages(currentChatId);
    const userMessage = { role: "user", text: message, time: getTime() };
    messages.push(userMessage);
    saveMessages(currentChatId, messages);
    addMessageUI("user", message);
    updateChatTitle(message);

    showTyping();
    $("sendBtn").disabled = true;
    $("messageInput").disabled = true;

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_id: currentChatId, message, profile: getProfile() })
        });

        const data = await response.json();
        hideTyping();
        const botText = data.response || "No response was returned.";

        const updatedMessages = getMessages(currentChatId);
        updatedMessages.push({ role: "bot", text: botText, time: getTime() });
        saveMessages(currentChatId, updatedMessages);
        addMessageUI("bot", botText);
    } catch (error) {
        console.error(error);
        hideTyping();
        addMessageUI("bot", "⚠️ I couldn't connect to the server. Make sure Flask is running.");
    }

    $("sendBtn").disabled = false;
    $("messageInput").disabled = false;
    $("messageInput").focus();
}

if ($("chatForm")) {
    $("chatForm").onsubmit = (event) => {
        event.preventDefault();
        const input = $("messageInput");
        const message = input.value.trim();
        if (!message) return;
        input.value = "";
        input.style.height = "auto";
        sendMessage(message);
    };
}

if ($("messageInput")) {
    $("messageInput").oninput = () => {
        const input = $("messageInput");
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 130) + "px";
    };
    $("messageInput").onkeydown = (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            $("chatForm").requestSubmit();
        }
    };
}

if ($("newChatBtn")) {
    $("newChatBtn").onclick = () => {
        createChat();
        $("messageInput").focus();
    };
}

if ($("mobileMenuBtn")) {
    $("mobileMenuBtn").onclick = () => { $("sidebar").classList.toggle("open"); };
}

async function loadBackendHistory(chatId) {
    try {
        const response = await fetch(`/history/${encodeURIComponent(chatId)}`);
        if (!response.ok) return;
        const data = await response.json();
        if (data.messages && data.messages.length) {
            saveMessages(chatId, data.messages);
            if (chatId === currentChatId) renderMessages(data.messages);
        }
    } catch (error) {
        console.warn("Could not load backend history:", error);
    }
}

setTheme(localStorage.getItem("theme") || "light");
currentUser = getCurrentUser();
if (currentUser) {
    loadProfileFromServer().finally(() => showAppScreen());
} else {
    showAuthScreen();
}

checkAuth();