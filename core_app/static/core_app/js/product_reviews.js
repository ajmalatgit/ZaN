(() => {
    const fieldset = document.querySelector('.review-rating-field');
    const form = document.querySelector('.review-form');
    if (!fieldset || !form) return;

    const choices = [...fieldset.querySelectorAll('.star-choice')];
    let selectedRating = Number(fieldset.querySelector('input:checked')?.value || 0);

    const paintStars = rating => {
        choices.forEach(choice => {
            const highlighted = Number(choice.dataset.rating) <= rating;
            choice.classList.toggle('is-highlighted', highlighted);
            choice.querySelector('.rating-choice-star').textContent =
                highlighted ? '★' : '☆';
        });
    };

    choices.forEach(choice => {
        const input = choice.querySelector('input');
        choice.addEventListener('pointerenter', event => {
            if (event.pointerType !== 'touch') paintStars(Number(choice.dataset.rating));
        });
        choice.addEventListener('focusin', () => paintStars(Number(choice.dataset.rating)));
        input.addEventListener('change', () => {
            selectedRating = Number(input.value);
            paintStars(selectedRating);
        });
    });

    fieldset.addEventListener('pointerleave', () => paintStars(selectedRating));
    fieldset.addEventListener('focusout', event => {
        if (!fieldset.contains(event.relatedTarget)) paintStars(selectedRating);
    });
    paintStars(selectedRating);

    form.addEventListener('click', event => {
        const suggestion = event.target.closest('[data-review-suggestion]');
        if (!suggestion) return;

        const textarea = form.querySelector('#reviewBody');
        if (!textarea) return;
        const sentence = suggestion.dataset.reviewSuggestion;
        textarea.value = textarea.value.trim()
            ? `${textarea.value.trim()} ${sentence}`
            : sentence;
        textarea.focus();
    });
})();
