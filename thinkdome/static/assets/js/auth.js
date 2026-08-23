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
    const roleField = document.getElementById('roleField');

    if (loginTab) loginTab.classList.toggle('active', mode === 'login');
    if (registerTab) registerTab.classList.toggle('active', mode === 'register');
    if (roleField) roleField.style.display = mode === 'register' ? 'block' : 'none';

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

// 2. Access app submission handler
async function enterApp(e) {
    if (e) e.preventDefault();

    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const roleInput = document.getElementById('userRole');
    if (!usernameInput || !passwordInput) return;

    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();
    const selectedRole = roleInput ? roleInput.value : 'AGENT_STANDARD';

    const loginAlert = document.getElementById('loginAlert');
    if (loginAlert) loginAlert.style.display = 'none';

    if (!username || !password) {
        if (loginAlert) {
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
            const { data, error } = await window.API.register(username, password, selectedRole);
            if (error) {
                throw new Error(error);
            }
            localStorage.setItem('thinkdome_user_role', selectedRole);
            if (loginAlert) {
                loginAlert.className = 'alert alert-success';
                loginAlert.textContent = `Account registered with role '${selectedRole}'! You can now log in.`;
                loginAlert.style.display = 'block';
            } else {
                alert(`Account registered with role '${selectedRole}'! You can now log in.`);
            }
            setAuthTab('login');
        } else {
            const { data, error } = await window.API.login(username, password);
            if (error) {
                throw new Error(error);
            }
            
            // Set logged in session flags in local storage
            localStorage.setItem('thinkdome_logged_in', 'true');
            const assignedRole = (data && data.user && data.user.role) || (data && data.role) || (username.toLowerCase().includes('admin') ? 'SUPER_ADMIN' : 'AGENT_STANDARD');
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
                
                // Trigger initialization/rendering functions in app.js if they exist
                if (typeof switchProject === 'function') switchProject('demo');
                if (typeof renderAllViews === 'function') renderAllViews();
            } else {
                // Multi-page page redirect to main dashboard
                window.location.href = 'index.html';
            }
        }
    } catch (err) {
        if (loginAlert) {
            loginAlert.className = 'alert alert-error';
            loginAlert.textContent = err.message || "Authentication failed.";
            loginAlert.style.display = 'block';
        } else if (typeof showCustomAlert === 'function') {
            await showCustomAlert("Authentication Failure", err.message || "Request failed.");
        } else {
            alert("Authentication Failure: " + (err.message || "Request failed."));
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
            // Trigger initialization/rendering in app.js if they are loaded
            if (typeof switchProject === 'function') switchProject('demo');
            if (typeof renderAllViews === 'function') renderAllViews();
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
