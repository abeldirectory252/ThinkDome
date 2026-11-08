// static/js/auth.js

let authMode = 'login';

function togglePasswordVisibility() {
    const pwdInput = document.getElementById('password');
    const eyeIcon = document.getElementById('pwdEyeIcon');
    if (!pwdInput) return;

    if (pwdInput.type === 'password') {
        pwdInput.type = 'text';
        if (eyeIcon) {
            eyeIcon.innerHTML = `<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.52 13.52 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/>`;
        }
    } else {
        pwdInput.type = 'password';
        if (eyeIcon) {
            eyeIcon.innerHTML = `<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>`;
        }
    }
}

// 1. Tab switching behavior
function setAuthTab(mode) {
    authMode = mode;
    const loginTab = document.getElementById('tabLogin');
    const registerTab = document.getElementById('tabRegister');
    const registrationDrawer = document.getElementById('authRegistrationDrawer');
    const passwordHint = document.getElementById('passwordHint');
    const extraProfile = document.getElementById('authExtraProfile');
    const toggleBtn = document.getElementById('btnToggleExtraProfile');
    const chevron = document.getElementById('extraProfileToggleChevron');

    if (loginTab) loginTab.classList.toggle('active', mode === 'login');
    if (registerTab) registerTab.classList.toggle('active', mode === 'register');

    if (registrationDrawer) {
        registrationDrawer.classList.toggle('open', mode === 'register');
    } else {
        const registrationFields = ['emailField', 'firstNameField', 'lastNameField'];
        registrationFields.forEach(id => {
            const field = document.getElementById(id);
            if (field) field.style.display = mode === 'register' ? 'block' : 'none';
        });
    }

    if (passwordHint) {
        passwordHint.style.display = mode === 'register' ? 'block' : 'none';
    }

    // When switching back to login, smoothly slide closed all extra fields ("cover it up")
    if (mode === 'login') {
        if (extraProfile) {
            extraProfile.classList.remove('open');
        }
        if (toggleBtn) {
            toggleBtn.classList.remove('open');
            toggleBtn.setAttribute('aria-expanded', 'false');
        }
        if (chevron) {
            chevron.style.transform = 'rotate(0deg)';
        }
        const wrap = document.querySelector('.login-wrap');
        if (wrap) wrap.scrollTo({ top: 0, behavior: 'smooth' });
    }

    const password = document.getElementById('password');
    if (password) password.autocomplete = mode === 'register' ? 'new-password' : 'current-password';

    const btn = document.querySelector('.submit-btn');
    if (btn) {
        if (mode === 'register') {
            btn.innerHTML = `
              Create Account
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14" />
                <path d="m12 5 7 7-7 7" />
              </svg>
            `;
        } else {
            btn.innerHTML = `
              Access Sandbox Workspace
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14" />
                <path d="m12 5 7 7-7 7" />
              </svg>
            `;
        }
    }
}

// Toggle slidable profile details accordion
function toggleExtraProfile() {
    const extraProfile = document.getElementById('authExtraProfile');
    const toggleBtn = document.getElementById('btnToggleExtraProfile');
    const chevron = document.getElementById('extraProfileToggleChevron');
    if (!extraProfile) return;

    const isOpen = extraProfile.classList.toggle('open');
    if (toggleBtn) {
        toggleBtn.classList.toggle('open', isOpen);
        toggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    if (chevron) {
        chevron.style.transform = isOpen ? 'rotate(180deg)' : 'rotate(0deg)';
    }

    if (isOpen) {
        // Smoothly ensure newly revealed fields slide into viewport smoothly
        setTimeout(() => {
            const wrap = document.querySelector('.login-wrap');
            if (wrap) {
                wrap.scrollBy({ top: 120, behavior: 'smooth' });
            }
        }, 120);
    }
}

// 2. Access app submission handler
async function enterApp(e) {
    if (e) e.preventDefault();

    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    if (!usernameInput || !passwordInput) return;

    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    const loginAlert = document.getElementById('loginAlert');
    if (loginAlert) loginAlert.style.display = 'none';

    if (!username || !password) {
        if (loginAlert) {
            loginAlert.className = 'alert alert-error';
            loginAlert.textContent = "Please enter both username and password to authenticate.";
            loginAlert.style.display = 'block';
        }
        return;
    }

    const btn = document.querySelector('.submit-btn');
    const originalBtnHTML = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="width: 14px; height: 14px; border-width: 1.5px; border-top-color: #fff; display: inline-block; vertical-align: middle; margin-right: 6px;"></span> Processing...`;
    }

    try {
        if (!window.API) {
            throw new Error("API Client not loaded.");
        }

        if (authMode === 'register') {
            const getVal = (id) => {
                const el = document.getElementById(id);
                return (el && el.value) ? el.value.trim() : '';
            };
            const email = getVal('email');
            const firstName = getVal('firstName');
            const lastName = getVal('lastName');
            const phone = getVal('phone');
            const organization = getVal('organization');
            const department = getVal('department');
            const designation = getVal('designation');

            if (!email || !firstName || !lastName) {
                throw new Error("Email, First name, and Last name are required for registration.");
            }

            const { data, error } = await window.API.register({
                username,
                password,
                email,
                first_name: firstName,
                last_name: lastName,
                phone,
                organization,
                department,
                department_id: department || undefined,
                designation,
            });
            if (error) {
                throw new Error(error);
            }
            if (loginAlert) {
                loginAlert.className = 'alert alert-success';
                loginAlert.textContent = 'Sandbox account created with standard agent access. You can now log in.';
                loginAlert.style.display = 'block';
            } else {
                alert('Sandbox account created. You can now log in.');
            }
            // Smoothly slide closed all registration fields and switch to login tab
            setAuthTab('login');
            passwordInput.value = '';
            passwordInput.focus();
        } else {
            const { data, error } = await window.API.login(username, password);
            if (error) {
                throw new Error(error);
            }
            
            // Set logged in session flags in local storage
            localStorage.setItem('thinkdome_logged_in', 'true');
            // The effective role is issued by the server after RBAC lookup.
            // Never derive a role from a client-side username convention.
            const assignedRole = (data && data.user && data.user.role) || (data && data.role) || 'AGENT_STANDARD';
            localStorage.setItem('thinkdome_user_role', assignedRole);

            const sessionToken = data && (data.session_token || data.access_token);
            if (sessionToken) {
                localStorage.setItem('thinkdome_token', sessionToken);
                localStorage.setItem('thinkdome_username', (data.user && data.user.username) || data.username || username);
            }

            // Adapt navigation UI based on logged-in role
            if (typeof applyRoleBasedUINavigation === 'function') {
                applyRoleBasedUINavigation(assignedRole, username);
            }

            const loginView = document.getElementById('loginView');
            const appView = document.getElementById('appView');
            
            if (appView) {
                // Single page configuration: toggle views in place
                if (loginView) loginView.style.display = 'none';
                appView.style.display = 'flex';

                if (typeof refreshWorkspaceMenu === 'function') refreshWorkspaceMenu();
                // Same-page login does not rerun DOMContentLoaded. Refresh all
                // authenticated data views now so loading placeholders resolve.
                if (typeof renderAllViews === 'function') renderAllViews();
            } else {
                // Multi-page page redirect to main dashboard
                window.location.href = 'index.html';
            }
        }
    } catch (err) {
        // Keep authentication failures on the same themed modal surface.
        // The API client de-duplicates an already-open validation modal.
        const message = err.message || "Authentication failed. Please try again.";
        if (message !== "SERVER_ERROR" && window.API && typeof window.API.showValidationErrorPopup === 'function') {
            window.API.showValidationErrorPopup(message);
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalBtnHTML;
        }
    }
}

// 3. Log out operation
async function logout() {
    const token = localStorage.getItem('thinkdome_token');
    if (token && window.API) {
        // fire-and-forget logout API call
        window.API.logout(token).catch(() => {});
    }

    localStorage.removeItem('thinkdome_logged_in');
    localStorage.removeItem('thinkdome_token');
    localStorage.removeItem('thinkdome_username');
    
    const loginView = document.getElementById('loginView');
    const appView = document.getElementById('appView');
    
    if (loginView && appView) {
        // Single page mode transition
        appView.style.display = 'none';
        loginView.style.display = 'flex';
    } else {
        // Redirect to login.html standalone screen
        window.location.href = 'login.html';
    }
}

// 4. Initial verification on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    const loginView = document.getElementById('loginView');
    const appView = document.getElementById('appView');
    
    const isLoggedIn = localStorage.getItem('thinkdome_logged_in') === 'true';
    
    if (isLoggedIn) {
        if (loginView) loginView.style.display = 'none';
        if (appView) {
            appView.style.display = 'flex';
            // app.js owns the server-manifest boot sequence. Do not render
            // static HTML pages or select a client-side default route here.
        } else {
            // Logged in but viewing standalone login, redirect to dashboard
            window.location.href = 'index.html';
        }
    } else {
        if (loginView) {
            loginView.style.display = 'flex';
        }
        if (appView) {
            appView.style.display = 'none';
        }
        if (!loginView && appView) {
            // Not logged in and on index.html with no loginView markup, redirect to login
            window.location.href = 'login.html';
        }
    }
});
function reloadSession() {
    // Re-read the current authenticated session and refresh dashboard state.
    window.location.reload();
}

// Explicit window bindings for inline HTML onclick/onsubmit handlers
window.setAuthTab = setAuthTab;
window.toggleExtraProfile = toggleExtraProfile;
window.togglePasswordVisibility = togglePasswordVisibility;
window.enterApp = enterApp;
window.logout = logout;
window.reloadSession = reloadSession;
