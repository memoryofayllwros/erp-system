/**
 * Enhanced Language Utility for Attendance System
 * Provides comprehensive language switching and translation capabilities
 */

class LanguageManager {
    constructor() {
        this.currentLanguage = this.detectInitialLanguage();
        this.translations = this.initializeTranslations();
        this.observers = [];
    }

    /**
     * Detect initial language from browser or stored preference
     */
    detectInitialLanguage() {
        // Check localStorage first
        const stored = localStorage.getItem('attendance_language');
        if (stored && ['zh', 'en'].includes(stored)) {
            return stored;
        }

        // Check if page content is in Chinese by looking at key elements
        const titleElement = document.querySelector('title');
        const statusElement = document.getElementById('status');
        const headingElement = document.querySelector('h2');
        
        // Check for Chinese characters in key elements
        const chineseElements = [titleElement, statusElement, headingElement].filter(el => el);
        for (const element of chineseElements) {
            if (element && this.isChinese(element.textContent)) {
                return 'zh';
            }
        }

        // Also check for Chinese content in data attributes
        const elementsWithData = document.querySelectorAll('[data-zh]');
        for (const element of elementsWithData) {
            const zhContent = element.getAttribute('data-zh');
            if (zhContent && this.isChinese(zhContent)) {
                return 'zh';
            }
        }

        // Check browser language as fallback
        const browserLang = navigator.language || navigator.userLanguage;
        if (browserLang.startsWith('zh')) {
            return 'zh';
        }
        
        return 'en'; // Default to English
    }

    /**
     * Initialize comprehensive translations
     */
    initializeTranslations() {
        return {
            zh: {
                // Page titles
                'Attendance Register': '打卡',
                'Special Attendance Register': '特殊簽到',
                'Special Attendance Register (EXIF)': '特殊簽到 (EXIF)',
                
                // Status messages
                'Getting location...': '獲取位置中...',
                'Location acquired': '位置已獲取',
                'Searching for nearby projects...': '正在搜尋附近項目...',
                'No nearby projects found. Please contact administrator.': '附近沒有找到工作項目。請聯繫管理員。',
                'Location acquired! Please select your work project.': '位置已獲取！請選擇你的工作項目。',
                'Unable to fetch nearby projects. Please try again.': '無法獲取附近項目。請再試一次。',
                'Please select a work project first.': '請先選擇工作項目。',
                'Submitting location...': '提交位置中...',
                'Attendance Register Succeed!': '打卡成功！',
                'Attendance Register Failed.': '打卡失敗。',
                'Network error. Please try again.': '網絡錯誤。請再試一次。',
                'Network error, please try again.': '網絡錯誤，請重試',
                
                // Error messages
                'Browser does not support geolocation. Please use a GPS-enabled device.': '瀏覽器不支援定位功能。請使用支援GPS的設備。',
                'Please allow location access in browser settings.': '請在瀏覽器設定中允許位置存取權限。',
                'Please ensure GPS is enabled and move to a better signal area.': '請確保GPS已開啟，並移至收訊較佳的位置。',
                'Request timeout. Please try again.': '請求超時。請再試一次。',
                'Unable to get location.': '無法獲取位置。',
                'Detected in-app browser. If location fails, please open in system browser (Safari/Chrome) and try again.': '檢測到你正使用應用內瀏覽器。若定位失敗，請點選右上角開啟於系統瀏覽器 (Safari/Chrome) 再試。',
                'This page is not loaded via secure connection (HTTPS), mobile may not be able to get location. Please use https link to open this page.': '此頁面並非透過安全連線 (HTTPS) 載入，手機可能無法取得定位。請使用 https 連結開啟此頁。',
                'Using in-app browser. If functionality is abnormal, please open with system browser.': '正使用應用內瀏覽器。若功能異常，請用系統瀏覽器開啟。',
                'Non-secure connection may affect location functionality. Please use HTTPS.': '非安全連線可能影響定位功能。請使用 HTTPS。',
                
                // Buttons and actions
                'Get My Location': '獲取我的位置',
                'Confirm': '確認',
                'Open Camera': '開啟相機',
                'Select Screenshot': '選擇截圖',
                'English': 'English',
                
                // Form labels
                'Select your work project:': '選擇你的工作項目: ',
                'Select project and upload image with location information': '選擇項目並上傳包含位置資訊的圖片',
                'Please select project and upload image with location information': '請選擇項目並上傳包含位置資訊的圖片',
                'Select Project': '選擇項目',
                'Select the project you want to register attendance to': '選擇您要打卡的項目',
                'Take a photo of a recognizable landmark or feature on-site': '拍攝現場具代表性的地標或特徵',
                'Take photos directly with camera': '直接使用相機拍攝',
                'Upload Google Maps screenshot': '上傳Google Maps截圖',
                'Upload map screenshot | sample screenshot': '上傳地圖截圖 | sample screenshot',
                
                // Data labels
                'Your location': '你的位置',
                'Project': '項目',
                'Time': '時間',
                'System will send confirmation message to your WhatsApp': '系統會自動發送確認訊息到您的WhatsApp',
                'System will send confirmation message to your WhatsApp': '系統將發送確認訊息到您的WhatsApp',
                
                // EXIF and technical
                'Image EXIF Information:': '圖片EXIF資訊: ',
                'GPS coordinates found': 'GPS座標已找到',
                'Latitude': '緯度',
                'Longitude': '經度',
                'Photo time': '拍攝時間',
                'Device': '設備',
                'Image has no GPS information, please use manual location': '圖片無GPS資訊，請使用手動定位',
                'Image has no GPS information, please upload map screenshot': '圖片無GPS資訊，請上傳地圖截圖',
                'Unable to read EXIF information, please upload map screenshot': '無法讀取EXIF資訊，請上傳地圖截圖',
                'GPS coordinates read from image': '已從圖片讀取GPS座標',
                'Reading photo EXIF information...': '讀取照片EXIF資訊...',
                'Map screenshot uploaded': '地圖截圖已上傳',
                
                // File upload
                'On-site Photo': '現場照片',
                'Map Screenshot': '地圖截圖',
                'Uploaded': '已上傳',
                'Source': '來源',
                'Photo EXIF GPS': '照片 EXIF GPS',
                'Photo': '照片',
                
                // Time and expiration
                'Link expires in': '連結將於',
                'minutes': '分鐘後過期',
                '⏳ Link expires in': '⏳ 連結將於',
                
                // Validation
                'Please upload at least one photo or screenshot': '請至少上傳一張照片或截圖',
                'Please select a project': '請選擇項目',
                'Please select an image file': '請選擇圖片檔案',
                'Unable to load projects': '無法載入項目',
                'Loading failed, please refresh': '載入失敗，請重新整理',
                'No available projects': '沒有可用項目',
                'Please select a project': '請選擇項目',
                'Loading projects...': '載入項目中...',
                'Project selected': '已選擇項目',
                
                // Success messages
                '📤 Submitting Attendance Info...': '📤  提交打卡資訊中...',
                '📤 Submitting Attendance Info...': '📤 提交打卡資訊中...',
                '🔍 Reading photo EXIF information...': '🔍 讀取照片EXIF資訊...',
                '🗺️ Map screenshot uploaded': '🗺️ 地圖截圖已上傳',
                '✅ GPS coordinates read from image': '✅ 已從圖片讀取GPS座標',
                '⚠️ Image has no GPS information, please upload map screenshot': '⚠️ 圖片無GPS資訊，請上傳地圖截圖',
                '⚠️ Unable to read EXIF information, please upload map screenshot': '⚠️ 無法讀取EXIF資訊，請上傳地圖截圖',
                '✅ Attendance Register Succeed!': '✅ 打卡成功！',
                '❌ Attendance Register Failed.': '❌ 打卡失敗。',

                // Additional success message translations
                '✅ Attendance Register Succeed!': '✅ 打卡成功！',
                'Uploaded': '已上傳',
                'Source': '來源',
                'Project': '項目',
                'Time': '時間',
                'System will send confirmation message to your WhatsApp': '系統將發送確認訊息到您的WhatsApp'
            },
            en: {
                // Reverse mappings for English to Chinese
                '打卡': 'Attendance Register',
                '📍 打卡': '📍 Attendance Register',
                '特殊簽到': 'Special Attendance Register',
                '特殊簽到 (EXIF)': 'Special Attendance Register (EXIF)',
                '獲取位置中...': 'Getting location...',
                '位置已獲取': 'Location acquired',
                '正在搜尋附近項目...': 'Searching for nearby projects...',
                '附近沒有找到工作項目。請聯繫管理員。': 'No nearby projects found. Please contact administrator.',
                '位置已獲取！請選擇你的工作項目。': 'Location acquired! Please select your work project.',
                '無法獲取附近項目。請再試一次。': 'Unable to fetch nearby projects. Please try again.',
                '請先選擇工作項目。': 'Please select a work project first.',
                '提交位置中...': 'Submitting location...',
                '打卡成功！': 'Attendance Register Succeed!',
                '打卡失敗。': 'Attendance Register Failed.',
                '網絡錯誤。請再試一次。': 'Network error. Please try again.',
                '網絡錯誤，請重試': 'Network error, please try again.',
                '瀏覽器不支援定位功能。請使用支援GPS的設備。': 'Browser does not support geolocation. Please use a GPS-enabled device.',
                '請在瀏覽器設定中允許位置存取權限。': 'Please allow location access in browser settings.',
                '請確保GPS已開啟，並移至收訊較佳的位置。': 'Please ensure GPS is enabled and move to a better signal area.',
                '請求超時。請再試一次。': 'Request timeout. Please try again.',
                '無法獲取位置。': 'Unable to get location.',
                '檢測到你正使用應用內瀏覽器。若定位失敗，請點選右上角開啟於系統瀏覽器 (Safari/Chrome) 再試。': 'Detected in-app browser. If location fails, please open in system browser (Safari/Chrome) and try again.',
                '此頁面並非透過安全連線 (HTTPS) 載入，手機可能無法取得定位。請使用 https 連結開啟此頁。': 'This page is not loaded via secure connection (HTTPS), mobile may not be able to get location. Please use https link to open this page.',
                '正使用應用內瀏覽器。若功能異常，請用系統瀏覽器開啟。': 'Using in-app browser. If functionality is abnormal, please open with system browser.',
                '非安全連線可能影響定位功能。請使用 HTTPS。': 'Non-secure connection may affect location functionality. Please use HTTPS.',
                '獲取我的位置': 'Get My Location',
                '確認': 'Confirm',
                '開啟相機': 'Open Camera',
                '選擇截圖': 'Select Screenshot',
                '🇭🇰 繁體中文': '🇭🇰 繁體中文',
                '選擇你的工作項目: ': 'Select your work project:',
                '選擇項目並上傳包含位置資訊的圖片': 'Select project and upload images with location information',
                '請選擇項目並上傳包含位置資訊的圖片': 'Please select project and upload images with location information',
                '選擇項目': 'Select Project',
                '選擇您要打卡的項目': 'Select the project you want to register attendance to',
                '拍攝現場具代表性的地標或特徵': 'Take a photo of a recognizable landmark or feature on-site',
                '直接使用相機拍攝': 'Take photos directly with camera',
                '上傳Google Maps截圖': 'Upload Google Maps screenshot',
                '上傳地圖截圖 | sample screenshot': 'Upload map screenshot | sample screenshot',
                '你的位置': 'Your location',
                '項目': 'Project',
                '時間': 'Time',
                '系統會自動發送確認訊息到您的WhatsApp': 'System will send confirmation message to your WhatsApp',
                '系統將發送確認訊息到您的WhatsApp': 'System will send confirmation message to your WhatsApp',
                '圖片EXIF資訊: ': 'Image EXIF Information:',
                'GPS座標已找到': 'GPS coordinates found',
                '緯度': 'Latitude',
                '經度': 'Longitude',
                '拍攝時間': 'Photo time',
                '設備': 'Device',
                '圖片無GPS資訊，請使用手動定位': 'Image has no GPS information, please use manual location',
                '圖片無GPS資訊，請上傳地圖截圖': 'Image has no GPS information, please upload map screenshot',
                '無法讀取EXIF資訊，請上傳地圖截圖': 'Unable to read EXIF information, please upload map screenshot',
                '已從圖片讀取GPS座標': 'GPS coordinates read from image',
                '讀取照片EXIF資訊...': 'Reading photo EXIF information...',
                '地圖截圖已上傳': 'Map screenshot uploaded',
                '現場照片': 'On-site Photo',
                '地圖截圖': 'Map Screenshot',
                '已上傳': 'Uploaded',
                '來源': 'Source',
                '照片 EXIF GPS': 'Photo EXIF GPS',
                '照片': 'Photo',
                '連結將於': 'Link expires in',
                '分鐘後過期': 'minutes',
                '⏳ 連結將於': '⏳ Link expires in',
                '請至少上傳一張照片或截圖': 'Please upload at least one photo or screenshot',
                '請選擇項目': 'Please select a project',
                '請選擇圖片檔案': 'Please select an image file',
                '無法載入項目': 'Unable to load projects',
                '載入失敗，請重新整理': 'Loading failed, please refresh',
                '沒有可用項目': 'No available projects',
                '載入項目中...': 'Loading projects...',
                '已選擇項目': 'Project selected',
                '📤 提交打卡資訊中...': 'Submitting Attendance Info...',
                '📤 提交打卡資訊中...': '📤 Submitting Attendance Info...',
                '🔍 讀取照片EXIF資訊...': '🔍 Reading photo EXIF information...',
                '🗺️ 地圖截圖已上傳': '🗺️ Map screenshot uploaded',
                '✅ 已從圖片讀取GPS座標': '✅ GPS coordinates read from image',
                '⚠️ 圖片無GPS資訊，請上傳地圖截圖': '⚠️ Image has no GPS information, please upload map screenshot',
                '⚠️ 無法讀取EXIF資訊，請上傳地圖截圖': '⚠️ Unable to read EXIF information, please upload map screenshot',
                '✅ 打卡成功！': '✅ Attendance Register Succeed!',
                '❌ 打卡失敗。': '❌ Attendance Register Failed.',
                '✅ 已選擇項目': '✅ Project selected',
                
            }
        };
    }

    /**
     * Toggle between languages
     */
    toggleLanguage() {
        this.currentLanguage = this.currentLanguage === 'zh' ? 'en' : 'zh';
        this.saveLanguagePreference();
        this.updateAllElements();
        this.notifyObservers();
    }

    /**
     * Set specific language
     */
    setLanguage(language) {
        if (['zh', 'en'].includes(language)) {
            this.currentLanguage = language;
            this.saveLanguagePreference();
            this.updateAllElements();
            this.notifyObservers();
        }
    }

    /**
     * Save language preference to localStorage
     */
    saveLanguagePreference() {
        localStorage.setItem('attendance_language', this.currentLanguage);
    }

    /**
     * Translate text based on current language
     */
    translate(text) {
        if (!text) return text;
        
        const translation = this.translations[this.currentLanguage][text];
        return translation || text;
    }

    /**
     * Update all elements with data attributes
     */
    updateAllElements() {
        // Update elements with data-zh and data-en attributes
        document.querySelectorAll('[data-zh][data-en]').forEach(element => {
            const translation = element.getAttribute(`data-${this.currentLanguage}`);
            if (translation) {
                element.textContent = translation;
            }
        });

        // Update title
        const titleElement = document.querySelector('title');
        if (titleElement) {
            const titleTranslation = titleElement.getAttribute(`data-${this.currentLanguage}`);
            if (titleTranslation) {
                document.title = titleTranslation;
            }
        }

        // Update language dropdown display
        this.updateLanguageDropdown();
    }

    /**
     * Update language dropdown display
     */
    updateLanguageDropdown() {
        const currentLanguageSpan = document.getElementById('current-language');
        if (currentLanguageSpan) {
            if (this.currentLanguage === 'zh') {
                currentLanguageSpan.textContent = '🇭🇰 繁體中文';
            } else {
                currentLanguageSpan.textContent = '🇺🇸 English';
            }
        }

        // Update selected state in dropdown options
        document.querySelectorAll('.language-option').forEach(option => {
            option.classList.remove('selected');
        });
        const selectedOption = document.querySelector(`[data-lang="${this.currentLanguage}"]`);
        if (selectedOption) {
            selectedOption.classList.add('selected');
        }
    }

    /**
     * Update status message with translation
     */
    updateStatus(message, type = 'info') {
        const translatedMessage = this.translate(message);
        const statusEl = document.getElementById('status');
        if (statusEl) {
            statusEl.innerHTML = translatedMessage;
            statusEl.className = type;
        }
    }

    /**
     * Add observer for language change events
     */
    addObserver(callback) {
        this.observers.push(callback);
    }

    /**
     * Remove observer
     */
    removeObserver(callback) {
        const index = this.observers.indexOf(callback);
        if (index > -1) {
            this.observers.splice(index, 1);
        }
    }

    /**
     * Notify all observers of language change
     */
    notifyObservers() {
        this.observers.forEach(callback => {
            try {
                callback(this.currentLanguage);
            } catch (error) {
                console.error('Error in language observer:', error);
            }
        });
    }

    /**
     * Get current language
     */
    getCurrentLanguage() {
        return this.currentLanguage;
    }

    /**
     * Check if text is in Chinese
     */
    isChinese(text) {
        return /[\u4e00-\u9fff]/.test(text);
    }

    /**
     * Check if text is in English
     */
    isEnglish(text) {
        return /^[a-zA-Z\s.,!?;:'"()-]+$/.test(text);
    }

    /**
     * Auto-detect language of text
     */
    detectLanguage(text) {
        if (this.isChinese(text)) return 'zh';
        if (this.isEnglish(text)) return 'en';
        return 'unknown';
    }
}

// Create global instance
window.languageManager = new LanguageManager();

// Auto-initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    window.languageManager.updateAllElements();
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LanguageManager;
}
