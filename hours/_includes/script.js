"use strict";

function setWeekSecondsElapsed(date, opts) {
	const dateIsNow = !date;
	if (dateIsNow) {
		date = new Date();
	}

	/* total seconds elapsed since Sunday 00:00:00 */
	const totalSecondsElapsed = date.getDay() * 86400 + date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds();
	document.documentElement.style.setProperty('--week-seconds-elapsed', `${totalSecondsElapsed}s`);

	/* update slider unless we're handling slider input */
	if (!opts?.slider) {
		document.getElementById('time-machine-slider').value = (totalSecondsElapsed - 24 * 3600 + 604800) % 604800;
	}

	/* pause CSS animation for time-machine input */
	if (opts?.timeTravelling) {
		document.getElementById('opening-hours').classList.add('time-travelling');
	} else {
		document.getElementById('opening-hours').classList.remove('time-travelling');
	}

	/* scroll to current day */
	if (opts?.scroll) {
		const day = new Date(date - 4 * 3600 * 1000 /* make days start at 4am */).getDay();
		document.querySelector(`thead th.day[data-day="${day}"]`).scrollIntoView({ behavior: 'smooth', inline: 'end' });
	}

	/* check for time zone mismatch */
	const warningTimeZoneMismatch = document.getElementById('warning-time-zone-mismatch');
	warningTimeZoneMismatch.hidden = !dateIsNow
		|| date.toLocaleString('sv') == date.toLocaleString('sv', { timeZone: 'Europe/London' });
}

/* tell CSS what time it is, scroll current day into view */
setWeekSecondsElapsed(null, { scroll: true });

/* sync CSS animations every 10 seconds and also when document becomes visible after being hidden */
/* (we used to rely on CSS animations fully but the drift was unpredictable and CPU usage too high) */
function syncCSSAnimations() {
	if (!document.hidden && !document.querySelector('table#opening-hours').classList.contains('time-travelling')) {
		setWeekSecondsElapsed(null); /* don't scroll */
	}
}
setInterval(syncCSSAnimations, 10_000);
document.addEventListener('visibilitychange', syncCSSAnimations);

/* -------------------------------------------------------------------------------- */

/* update animation time on time-machine input */
document.getElementById('time-machine').addEventListener('input', (e) => {
	const selectedDate = new Date(e.target.value);
	setWeekSecondsElapsed(isNaN(selectedDate) ? null : selectedDate, { scroll: true, timeTravelling: !isNaN(selectedDate)});
});

/* see https://dev.to/kevinluo201/set-value-of-datetime-local-input-field-3435 */
function convertToDateTimeLocalString(date) {
	const year = date.getFullYear();
	const month = (date.getMonth() + 1).toString().padStart(2, '0');
	const day = date.getDate().toString().padStart(2, '0');
	const hours = date.getHours().toString().padStart(2, '0');
	const minutes = date.getMinutes().toString().padStart(2, '0');

	return `${year}-${month}-${day}T${hours}:${minutes}`;
}

/* update time-machine and animation time on time-machine-slider input */
document.getElementById('time-machine-slider').addEventListener('input', (e) => {
	const rangeSecondsElapsed = (e.target.valueAsNumber + 24 * 3600) % 604800;

	const now = new Date();
	const nowSecondsElapsed = now.getDay() * 86400 + now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();

	const date = new Date(now.valueOf() + (rangeSecondsElapsed - nowSecondsElapsed) * 1000);
	document.getElementById('time-machine').value = convertToDateTimeLocalString(date);
	setWeekSecondsElapsed(date, { slider: true, timeTravelling: true });
});

/* -------------------------------------------------------------------------------- */

/* async wrapper for getCurrentPosition */
function getCurrentPosition(options) {
	return new Promise((resolve, reject) => {
		if (navigator.geolocation) {
			navigator.geolocation.getCurrentPosition(resolve, reject, options);
		} else {
			reject(new Error('Geolocation is not supported by your browser'));
		}
	});
}

async function getCurrentPositionWithIndicator(options) {
	const indicator = document.querySelector('div#location-indicator');
	try {
		indicator.classList.remove('hidden');
		return await getCurrentPosition(options);
	} finally {
		indicator.classList.add('hidden');
	}
}

/* haversine formula */
function getDistance(lat1, lon1, lat2, lon2) {
	const R = 6371; /* radius of the Earth in km */
	const dLat = (lat2 - lat1) * Math.PI / 180;
	const dLon = (lon2 - lon1) * Math.PI / 180;

	const a = 
		Math.sin(dLat / 2) * Math.sin(dLat / 2) +
		Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) * Math.sin(dLon / 2);

	const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
	return R * c; /* distance in km */
}

/* -------------------------------------------------------------------------------- */

/* counter to track the latest sort request and ignore stale geolocation results */
let lastSortId = 0;

/* sort venues - compareFn takes a pair of <tr> elements and return one of -1, 0, 1 */
async function sortVenuesBy(getCompareFn) {
	const currentSortId = ++lastSortId;
	const compareFn = await getCompareFn();
	if (currentSortId !== lastSortId)
		return; /* skip if another sort happened in the meantime */

	document.querySelectorAll('table#opening-hours > tbody').forEach((tbody) => {
		/* sort each tbody separately */
		[...tbody.children].filter((e) =>
			e.classList.contains('venue')
		).sort(compareFn).reduceRight((acc, x) =>
			tbody.insertBefore(x, acc)
		);
	});
}

async function sortVenuesByName() {
	const collator = new Intl.Collator('en');
	const getText = (tr) => tr.querySelector('th.venue').innerText;
	await sortVenuesBy(async () => (a, b) => collator.compare(getText(a), getText(b)));
}

async function sortVenuesByDay(day, field, reverse) {
	function getFieldValue(tr) {
		const value = tr.querySelector(`td.day[data-day="${day}"]`).dataset[field];
		return value ? (reverse ? -1 : 1) * parseFloat(value) : Infinity;
	}
	await sortVenuesBy(async () => (a, b) => getFieldValue(a) - getFieldValue(b));
}

async function sortVenuesByDistance() {
	await sortVenuesBy(async () => {
		const position = await getCurrentPositionWithIndicator({
			enableHighAccuracy: true,
			timeout: 10000,
			maximumAge: 60 * 1000,
		});

		/* calculate and store distances */
		[...document.querySelectorAll('table#opening-hours > tbody th.venue')].forEach((venue) => {
			venue.dataset.distance = getDistance(
				venue.dataset.locLat, venue.dataset.locLng,
				position.coords.latitude, position.coords.longitude
			);
		});

		const getVenueDistance = (tr) => tr.querySelector('th.venue').dataset.distance;
		return (a, b) => getVenueDistance(a) - getVenueDistance(b);
	});
}

/* sort by distance by default if permission already granted */
async function sortVenuesByDistanceIfPermitted() {
	try {
		const p = await navigator.permissions.query({ name: "geolocation" });
		if (p.state === 'granted') {
			await sortVenuesByDistance();
		}
	} catch (error) {
		console.error(error);
	}
}

document.getElementById('sort-name').addEventListener('click', () => sortVenuesByName());
document.getElementById('sort-distance').addEventListener('click', () => sortVenuesByDistance());
document.querySelectorAll('button.sort-first-open').forEach((b) =>
	b.addEventListener('click', () => sortVenuesByDay(b.parentElement.dataset.day, 'firstOpen', false)));
document.querySelectorAll('button.sort-last-close').forEach((b) =>
	b.addEventListener('click', () => sortVenuesByDay(b.parentElement.dataset.day, 'lastClose', true)));

sortVenuesByDistanceIfPermitted();

/* -------------------------------------------------------------------------------- */

/* Clock format toggle (12h/24h) */
const use24hCheckbox = document.getElementById('use-24h-format');

/* Load saved preference from localStorage */
const saved24hPreference = localStorage.getItem('use24hFormat');
if (saved24hPreference !== null) {
	use24hCheckbox.checked = saved24hPreference === 'true';
}

/* Function to update all time displays based on format */
function updateTimeDisplays() {
	const use24h = use24hCheckbox.checked;

	document.querySelectorAll('td.day').forEach((cell) => {
		const currentHoursSpan = cell.querySelector('.opening-hours .current-hours');
		const regularHoursS = cell.querySelector('.opening-hours .regular-hours');

		if (currentHoursSpan) {
			const currentTime = use24h ? cell.dataset.time24hCurrent : cell.dataset.time12hCurrent;
			currentHoursSpan.textContent = currentTime;
		}

		if (regularHoursS) {
			const regularTime = use24h ? cell.dataset.time24hRegular : cell.dataset.time12hRegular;
			regularHoursS.textContent = regularTime;
		}
	});
}

/* Update displays on checkbox change */
use24hCheckbox.addEventListener('change', () => {
	localStorage.setItem('use24hFormat', use24hCheckbox.checked);
	updateTimeDisplays();
});

/* Initial update on page load */
updateTimeDisplays();
