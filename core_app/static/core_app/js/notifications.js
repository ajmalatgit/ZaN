(() => {
    const menu = document.querySelector('.notification-menu');
    if (!menu) return;

    const button = menu.querySelector('.notification-menu-toggle');
    const panel = menu.querySelector('.notification-panel');
    const list = menu.querySelector('.notification-list');
    const unreadDot = menu.querySelector('.notification-unread-dot');
    const unreadCount = menu.querySelector('.notification-unread-count');
    const storageKey = `zan.notifications.v1:${menu.dataset.userKey || 'guest'}`;

    const createDemoNotifications = () => {
        const now = Date.now();
        return [
            {
                id: 'welcome',
                title: 'Welcome to ZAN',
                message: 'Explore the latest additions to our collection.',
                createdAt: new Date(now - 12 * 60 * 1000).toISOString(),
                read: false
            },
            {
                id: 'order-update',
                title: 'Order update',
                message: 'Your recent order is being prepared for dispatch.',
                createdAt: new Date(now - 3 * 60 * 60 * 1000).toISOString(),
                read: false
            },
            {
                id: 'new-arrivals',
                title: 'New arrivals',
                message: 'Fresh styles have been added to the catalog.',
                createdAt: new Date(now - 26 * 60 * 60 * 1000).toISOString(),
                read: true
            }
        ];
    };

    const isNotification = item =>
        item &&
        typeof item.id === 'string' &&
        typeof item.title === 'string' &&
        typeof item.message === 'string' &&
        typeof item.createdAt === 'string' &&
        !Number.isNaN(Date.parse(item.createdAt)) &&
        typeof item.read === 'boolean';

    const readStoredNotifications = () => {
        try {
            const stored = window.localStorage.getItem(storageKey);
            if (stored === null) {
                const seeded = createDemoNotifications();
                saveNotifications(seeded);
                return seeded;
            }

            const parsed = JSON.parse(stored);
            if (!Array.isArray(parsed) || !parsed.every(isNotification)) {
                throw new TypeError('Stored notification data has an invalid format.');
            }
            return parsed;
        } catch (error) {
            console.error('Unable to load saved notifications; showing demo notifications.', error);
            return createDemoNotifications();
        }
    };

    const saveNotifications = items => {
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(items));
        } catch (error) {
            console.error('Unable to save notification changes in this browser.', error);
        }
    };

    let notifications = readStoredNotifications();

    const render = () => {
        const unread = notifications.filter(item => !item.read).length;
        unreadDot.hidden = unread === 0;
        button.setAttribute(
            'aria-label',
            unread ? `Notifications, ${unread} unread` : 'Notifications, all caught up'
        );
        unreadCount.textContent = unread ? `${unread} new` : 'All caught up';
        list.replaceChildren();

        if (notifications.length === 0) {
            const empty = document.createElement('li');
            empty.className = 'notification-empty';
            empty.textContent = 'You have no notifications.';
            list.appendChild(empty);
            return;
        }

        const dateFormatter = new Intl.DateTimeFormat(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short'
        });

        notifications
            .slice()
            .sort((first, second) => Date.parse(second.createdAt) - Date.parse(first.createdAt))
            .forEach(notification => {
                const item = document.createElement('li');
                item.className = `notification-item${notification.read ? '' : ' is-unread'}`;

                const content = document.createElement('div');
                content.className = 'notification-item-content';

                const title = document.createElement('strong');
                title.className = 'notification-item-title';
                title.textContent = notification.title;

                const message = document.createElement('span');
                message.className = 'notification-item-message';
                message.textContent = notification.message;

                const time = document.createElement('time');
                time.dateTime = notification.createdAt;
                time.textContent = dateFormatter.format(new Date(notification.createdAt));

                const remove = document.createElement('button');
                remove.className = 'notification-remove';
                remove.type = 'button';
                remove.dataset.notificationId = notification.id;
                remove.setAttribute('aria-label', `Remove notification: ${notification.title}`);
                remove.textContent = '×';

                content.append(title, message, time);
                item.append(content, remove);
                list.appendChild(item);
            });
    };

    const setOpen = open => {
        panel.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
        if (open) {
            notifications = notifications.map(item => ({ ...item, read: true }));
            saveNotifications(notifications);
            render();
        }
    };

    button.addEventListener('click', () => setOpen(panel.hidden));

    list.addEventListener('click', event => {
        const removeButton = event.target.closest('.notification-remove');
        if (!removeButton) return;

        notifications = notifications.filter(
            item => item.id !== removeButton.dataset.notificationId
        );
        saveNotifications(notifications);
        render();
    });

    document.addEventListener('click', event => {
        if (!menu.contains(event.target)) setOpen(false);
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') setOpen(false);
    });

    window.addEventListener('storage', event => {
        if (event.key !== storageKey || event.newValue === null) return;

        try {
            const updated = JSON.parse(event.newValue);
            if (!Array.isArray(updated) || !updated.every(isNotification)) {
                throw new TypeError('Stored notification data has an invalid format.');
            }
            notifications = updated;
            render();
        } catch (error) {
            console.error('Unable to sync notification changes from another tab.', error);
        }
    });

    render();
})();
