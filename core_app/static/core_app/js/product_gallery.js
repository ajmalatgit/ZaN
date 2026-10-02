(() => {
    const gallery = document.querySelector('.pdp-gallery');
    const viewer = document.getElementById('mediaViewer');
    if (!gallery || !viewer) return;

    const image = viewer.querySelector('.media-viewer-image');
    const stage = viewer.querySelector('.media-viewer-stage');
    const closeButton = viewer.querySelector('.media-viewer-close');
    let scale = 1;
    let offsetX = 0;
    let offsetY = 0;
    let pointerX = 0;
    let pointerY = 0;
    let dragging = false;
    let previousFocus = null;

    const renderTransform = () => {
        image.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
        stage.classList.toggle('is-zoomed', scale > 1);
    };

    const setScale = nextScale => {
        scale = Math.max(1, Math.min(5, nextScale));
        if (scale === 1) {
            offsetX = 0;
            offsetY = 0;
        }
        renderTransform();
    };

    const openViewer = trigger => {
        const source = trigger.dataset.viewerImage;
        if (!source) return;
        previousFocus = document.activeElement;
        image.src = source;
        image.alt = trigger.querySelector('img')?.alt || 'Product photo';
        viewer.hidden = false;
        document.body.classList.add('media-viewer-open');
        setScale(1);
        closeButton.focus();
    };

    const closeViewer = () => {
        if (viewer.hidden) return;
        viewer.hidden = true;
        image.removeAttribute('src');
        document.body.classList.remove('media-viewer-open');
        previousFocus?.focus();
    };

    document.addEventListener('click', event => {
        const trigger = event.target.closest('[data-viewer-image]');
        if (trigger) {
            openViewer(trigger);
        }
    });

    gallery.addEventListener('click', event => {
        const thumbnail = event.target.closest('[data-gallery-image]');
        if (!thumbnail) return;

        gallery.querySelectorAll('.thumb-item').forEach(item => {
            item.classList.toggle('active', item === thumbnail);
        });
        const primary = document.getElementById('primaryView');
        const mainTrigger = gallery.querySelector('.gallery-view-trigger');
        if (primary) primary.src = thumbnail.dataset.galleryImage;
        if (mainTrigger) mainTrigger.dataset.viewerImage = thumbnail.dataset.galleryImage;
    });

    viewer.addEventListener('click', event => {
        if (event.target === viewer || event.target.closest('.media-viewer-close')) {
            closeViewer();
            return;
        }

        const zoomButton = event.target.closest('[data-zoom]');
        if (zoomButton) {
            setScale(scale + (zoomButton.dataset.zoom === 'in' ? 0.5 : -0.5));
        }
    });

    viewer.addEventListener('wheel', event => {
        if (viewer.hidden) return;
        event.preventDefault();
        setScale(scale + (event.deltaY < 0 ? 0.2 : -0.2));
    }, { passive: false });

    stage.addEventListener('dblclick', () => setScale(scale === 1 ? 2 : 1));

    stage.addEventListener('pointerdown', event => {
        if (scale === 1) return;
        dragging = true;
        pointerX = event.clientX;
        pointerY = event.clientY;
        stage.setPointerCapture(event.pointerId);
    });

    stage.addEventListener('pointermove', event => {
        if (!dragging) return;
        offsetX += event.clientX - pointerX;
        offsetY += event.clientY - pointerY;
        pointerX = event.clientX;
        pointerY = event.clientY;
        renderTransform();
    });

    stage.addEventListener('pointerup', () => {
        dragging = false;
    });
    stage.addEventListener('pointercancel', () => {
        dragging = false;
    });

    closeButton.addEventListener('click', closeViewer);
    document.addEventListener('keydown', event => {
        if (viewer.hidden) return;
        if (event.key === 'Escape') closeViewer();
        if (event.key === '+' || event.key === '=') setScale(scale + 0.5);
        if (event.key === '-') setScale(scale - 0.5);
    });
})();
