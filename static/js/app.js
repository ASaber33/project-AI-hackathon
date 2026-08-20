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
const guestMessages = {};

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

function handleUnauthorized() {
    clearCurrentUser();
    showAuthScreen();
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
    if (currentUser?.guest) return [];
    try {
        const key = `${userStoragePrefix()}_chatIndex`;
        return JSON.parse(localStorage.getItem(key) || "[]");
    } catch {
        return [];
    }
}

function saveChats(chats) {
    if (currentUser?.guest) return;
    localStorage.setItem(`${userStoragePrefix()}_chatIndex`, JSON.stringify(chats));
}

function getMessages(chatId) {
    if (currentUser?.guest) return guestMessages[chatId] || [];
    try {
        const key = `${userStoragePrefix()}_messages_${chatId}`;
        return JSON.parse(localStorage.getItem(key) || "[]");
    } catch {
        return [];
    }
}

function saveMessages(chatId, messages) {
    if (currentUser?.guest) {
        guestMessages[chatId] = messages;
        return;
    }
    localStorage.setItem(`${userStoragePrefix()}_messages_${chatId}`, JSON.stringify(messages));
}

function escapeHTML(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}

function addAnswerContent(container, text) {
    const parts = text.split("\n\nSources\n");
    const answer = document.createElement("div");
    answer.textContent = parts[0];
    container.appendChild(answer);

    if (!parts[1]) return;

    const sources = document.createElement("div");
    sources.className = "source-list";
    parts[1].split("\n").filter(Boolean).forEach((line) => {
        const source = document.createElement("div");
        source.className = "source-item";
        const webMatch = line.match(/^- Web: (.+?) - (https?:\/\/\S+)/);
        const searchMatch = line.match(/^- Web search: (https?:\/\/\S+)/);
        const pdfMatch = line.match(/^- PDF: (.+?) - (\/guidelines\/\S+#page=\d+)$/);
        if (webMatch || searchMatch) {
            const link = document.createElement("a");
            const url = webMatch ? webMatch[2] : searchMatch[1];
            link.href = url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.className = "source-link";
            link.title = url;
            const logo = document.createElement("span");
            logo.className = "source-logo web-logo";
            logo.textContent = "↗";
            const label = document.createElement("span");
            label.textContent = webMatch ? webMatch[1] : "Web search";
            link.append(logo, label);
            source.appendChild(link);
        } else if (pdfMatch) {
            const label = document.createElement("a");
            label.href = pdfMatch[2];
            label.target = "_blank";
            label.rel = "noopener noreferrer";
            label.title = "Open PDF guideline";
            label.className = "source-link pdf-source";
            const logo = document.createElement("span");
            logo.className = "source-logo pdf-logo";
            logo.textContent = "PDF";
            label.append(logo, document.createTextNode(pdfMatch[1]));
            source.appendChild(label);
        } else {
            source.textContent = line;
        }
        sources.appendChild(source);
    });
    container.appendChild(sources);
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

const languageText = {
    en: { login: "Login", signup: "Create Account", guest: "Continue as Guest", newChat: "＋ New Chat", logout: "Logout", previous: "Previous Chats", placeholder: "Ask your clinical question..." },
    ar: { login: "تسجيل الدخول", signup: "إنشاء حساب", guest: "المتابعة كضيف", newChat: "＋ محادثة جديدة", logout: "تسجيل الخروج", previous: "المحادثات السابقة", placeholder: "اكتب سؤالك التنفسي..." },
};

function setLanguage(language) {
    const text = languageText[language] || languageText.en;
    document.documentElement.lang = language;
    document.body.dir = language === "ar" ? "rtl" : "ltr";
    if ($("loginForm")?.querySelector(".primary")) $("loginForm").querySelector(".primary").textContent = text.login;
    if ($("signupForm")?.querySelector(".primary")) $("signupForm").querySelector(".primary").textContent = text.signup;
    if ($("guestBtn")) $("guestBtn").textContent = text.guest;
    if ($("newChatBtn")) $("newChatBtn").textContent = text.newChat;
    if ($("logoutBtn")) $("logoutBtn").querySelector("span:last-child").textContent = text.logout;
    if ($("messageInput")) $("messageInput").placeholder = text.placeholder;
    localStorage.setItem("language", language);
    if ($("languageBtn")) $("languageBtn").textContent = language === "ar" ? "EN" : "ع";
}

function toggleLanguage() {
    setLanguage((localStorage.getItem("language") || "en") === "en" ? "ar" : "en");
}

function setFontScale(scale) {
    const safeScale = Math.max(0.9, Math.min(2, scale));
    document.documentElement.style.setProperty("--font-scale", safeScale);
    localStorage.setItem("fontScale", String(safeScale));
    if ($("fontSizeLabel")) $("fontSizeLabel").textContent = `${Math.round(safeScale * 100)}%`;
}

function updateProfileUI() {
    const profile = getProfile();
    const name = profile.name || currentUser?.name || "Profile";
    if ($("miniName")) $("miniName").textContent = name;
    if ($("miniPhoto")) {
        $("miniPhoto").src = profile.photo || DEFAULT_AVATAR;
    }
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
if ($("languageBtn")) $("languageBtn").onclick = toggleLanguage;
if ($("topProfileBtn")) $("topProfileBtn").onclick = openSettings;
if ($("closeSettingsBtn")) $("closeSettingsBtn").onclick = closeSettings;
if ($("settingsModal")) $("settingsModal").onclick = (event) => { if (event.target === $("settingsModal")) closeSettings(); };
if ($("fontDownBtn")) $("fontDownBtn").onclick = () => setFontScale(parseFloat(localStorage.getItem("fontScale") || "1") - 0.05);
if ($("fontUpBtn")) $("fontUpBtn").onclick = () => setFontScale(parseFloat(localStorage.getItem("fontScale") || "1") + 0.05);

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

if ($("guestBtn")) {
    $("guestBtn").onclick = async () => {
        try {
            const response = await fetch("/auth/guest", { method: "POST" });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || "Guest mode is unavailable.");
            currentUser = data.user;
            currentChatId = null;
            await showAppScreen();
        } catch (error) {
            alert(error.message);
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

async function showAppScreen() {
    $("welcomeScreen").classList.add("hidden");
    $("app").classList.remove("hidden");
    currentChatId = null;
    localStorage.removeItem("currentChatId");
    setTheme(localStorage.getItem("theme") || "light");
    updateProfileUI();
    loadUsage();
    await loadBackendChats();
    renderChatList();
    renderMessages([]);
    $("messageInput")?.focus();
}

async function loadUsage() {
    try {
        const response = await fetch("/usage");
        if (!response.ok) return;
        const data = await response.json();
        if (data.success && $("usageCounter")) {
            $("usageCounter").textContent = `${data.used}/${data.limit}`;
        }
    } catch (error) {
        console.warn("Usage load failed", error);
    }
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
    saveMessages(id, []);
    currentChatId = id;
    localStorage.setItem("currentChatId", id);
    renderMessages([]);
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

async function loadBackendChats() {
    try {
        const response = await fetch("/chats");
        if (!response.ok) return;
        const data = await response.json();
        if (!data.success || !Array.isArray(data.chats)) return;

        const localChats = getChats().filter((chat) => getMessages(chat.id).length > 0);
        const localById = new Map(localChats.map((chat) => [chat.id, chat]));
        data.chats.forEach((chat) => {
            const local = localById.get(chat.id);
            localById.set(chat.id, { ...chat, ...(local || {}) });
        });
        const chats = Array.from(localById.values()).sort(
            (a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0)
        );
        saveChats(chats);
        if (currentChatId && !chats.some((chat) => chat.id === currentChatId)) {
            currentChatId = null;
            localStorage.removeItem("currentChatId");
        }
    } catch (error) {
        console.warn("Could not load chat list:", error);
    }
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
            <button class="delete-chat-btn" title="Delete chat" aria-label="Delete chat" onclick="event.stopPropagation(); deleteChat('${chat.id}')">×</button>
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
    updateSuggestions(messages);
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
    if (isUser) {
        content.textContent = text;
    } else {
        addAnswerContent(content, text);
    }
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

const suggestionSets = {
    breathing: ["متى يكون ضيق التنفس خطيرًا؟", "ما أسباب الصفير في الصدر؟", "كيف أخفف الكحة بأمان؟", "متى أحتاج للطوارئ؟"],
    allergy: ["كيف أخفف أعراض الحساسية؟", "ما الفرق بين الحساسية والبرد؟", "هل المحلول الملحي مفيد؟", "متى أراجع الطبيب؟"],
    digestive: ["هل الارتجاع يسبب كحة؟", "هل الحموضة قد تسبب ضيق النفس؟", "متى أراجع الطبيب بسبب كحة ليلية؟", "هل أحتاج تقييمًا للصدر؟"],
    headache: ["هل الصداع مع ضيق النفس خطير؟", "هل الدوخة مع صعوبة التنفس تستدعي الطوارئ؟", "ما علامات نقص الأكسجين؟", "متى أحتاج فحصًا عاجلًا؟"],
    stress: ["هل القلق يسبب ضيق النفس؟", "ما تمارين التنفس الآمنة؟", "كيف أفرق بين القلق ونوبة الربو؟", "متى أطلب مساعدة عاجلة؟"],
    medicine: ["ما الآثار الجانبية لأدوية الحساسية؟", "هل يتعارض دواء الحساسية مع أدوية أخرى؟", "هل يناسب دواء الكحة الأطفال؟", "متى أوقف الدواء وأراجع الطبيب؟"],
    general: ["ما الأعراض التنفسية التي تستدعي الطبيب؟", "ما الخطوات الآمنة لتخفيف الكحة؟", "ما المعلومات المهمة عن ضيق النفس؟", "متى أحتاج إلى طوارئ بسبب التنفس؟"],
};

function updateSuggestions(messages = []) {
    const lastUserMessage = [...messages].reverse().find((message) => message.role === "user");
    const text = (lastUserMessage?.text || "").toLowerCase();
    let category = "general";
    if (/تنفس|نهجان|نهج|صدر|كحه|كحة|صفير|بلغم|اختناق/.test(text)) category = "breathing";
    else if (/حساسيه|حساسية|رشح|عطس|حكة|حكه/.test(text)) category = "allergy";
    else if (/بطن|معده|معدة|حموضه|حموضة|غثيان|قيء|اسهال|إسهال/.test(text)) category = "digestive";
    else if (/صداع|دوخه|دوخة|رأس|راس|خفقان/.test(text)) category = "headache";
    else if (/توتر|قلق|نوم|نائم|أرق|ارق/.test(text)) category = "stress";
    else if (/دواء|علاج|حبوب|جرعة|جرعه|مضاد/.test(text)) category = "medicine";
    document.querySelectorAll(".suggestion").forEach((button, index) => {
        button.textContent = suggestionSets[category][index];
    });
}

async function sendMessage(message) {
    ensureChat();
    const messages = getMessages(currentChatId);
    const userMessage = { role: "user", text: message, time: getTime() };
    messages.push(userMessage);
    saveMessages(currentChatId, messages);
    const chatList = getChats();
    if (!chatList.some((chat) => chat.id === currentChatId)) {
        chatList.unshift({
            id: currentChatId,
            title: "New conversation",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        });
        saveChats(chatList);
    }
    addMessageUI("user", message);
    updateChatTitle(message);
    updateSuggestions(messages);

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
        if (response.status === 401) {
            hideTyping();
            handleUnauthorized();
            alert("Your session expired. Please log in again.");
            return;
        }
        if (!response.ok) {
            throw new Error(data.error || "The assistant could not complete the request.");
        }
        if (data.daily_limit_exhausted) {
            if ($("usageCounter")) $("usageCounter").textContent = `${data.used_messages}/${data.daily_limit}`;
        } else {
            loadUsage();
        }
        hideTyping();
        const botText = data.response || "The assistant returned an empty response. Please try again.";

        const updatedMessages = getMessages(currentChatId);
        updatedMessages.push({ role: "bot", text: botText, time: getTime() });
        saveMessages(currentChatId, updatedMessages);
        addMessageUI("bot", botText);
    } catch (error) {
        console.error(error);
        hideTyping();
        addMessageUI("bot", `⚠️ ${error.message || "I couldn't connect to the server."}`);
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

document.querySelectorAll(".suggestion").forEach((button) => {
    button.onclick = () => {
        const input = $("messageInput");
        if (!input || input.disabled) return;
        input.value = button.textContent.trim();
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
    };
});

if ($("newChatBtn")) {
    $("newChatBtn").onclick = () => {
        createChat();
        $("messageInput").focus();
    };
}

if ($("mobileMenuBtn")) {
    $("mobileMenuBtn").onclick = () => { $("sidebar").classList.toggle("open"); };
}

if ($("sidebar")) {
    const sidebar = $("sidebar");
    let touchStartX = 0;
    let touchStartY = 0;
    let touchAxis = null;

    sidebar.addEventListener("touchstart", (event) => {
        if (!sidebar.classList.contains("open") || event.touches.length !== 1) return;
        touchStartX = event.touches[0].clientX;
        touchStartY = event.touches[0].clientY;
        touchAxis = null;
    }, { passive: true });

    sidebar.addEventListener("touchmove", (event) => {
        if (!sidebar.classList.contains("open") || event.touches.length !== 1) return;
        const deltaX = event.touches[0].clientX - touchStartX;
        const deltaY = event.touches[0].clientY - touchStartY;

        if (!touchAxis && (Math.abs(deltaX) > 8 || Math.abs(deltaY) > 8)) {
            touchAxis = Math.abs(deltaX) > Math.abs(deltaY) ? "horizontal" : "vertical";
        }
        if (touchAxis !== "horizontal" || deltaX >= 0) return;

        sidebar.classList.add("swiping");
        sidebar.style.transform = `translateX(${Math.max(deltaX, -sidebar.offsetWidth)}px)`;
        event.preventDefault();
    }, { passive: false });

    const finishSidebarSwipe = (event) => {
        if (!sidebar.classList.contains("swiping")) return;
        const endX = event.changedTouches?.[0]?.clientX ?? touchStartX;
        const shouldClose = endX - touchStartX < -70;
        sidebar.classList.remove("swiping");
        sidebar.style.transform = "";
        if (shouldClose) sidebar.classList.remove("open");
    };

    sidebar.addEventListener("touchend", finishSidebarSwipe, { passive: true });
    sidebar.addEventListener("touchcancel", finishSidebarSwipe, { passive: true });
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
setLanguage(localStorage.getItem("language") || "en");
setFontScale(parseFloat(localStorage.getItem("fontScale") || "1"));
currentUser = getCurrentUser();
if (currentUser) {
    loadProfileFromServer().finally(() => showAppScreen());
} else {
    showAuthScreen();
}

checkAuth();