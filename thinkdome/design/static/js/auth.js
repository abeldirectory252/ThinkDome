// static/js/auth.js

// 1. Tab switching behavior
function setAuthTab(mode) {
    const loginTab = document.getElementById('tabLogin');
    const registerTab = document.getElementById('tabRegister');
    if (loginTab) loginTab.classList.toggle('active', mode === 'login');
    if (registerTab) registerTab.classList.toggle('active', mode === 'register');
}

// 2. Access app submission handler
function enterApp(e) {
    if (e) e.preventDefault();
    
    // Set logged in session flag in local storage
    localStorage.setItem('thinkdome_logged_in', 'true');
    
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

// 3. Log out operation
function logout() {
    localStorage.removeItem('thinkdome_logged_in');
    
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
