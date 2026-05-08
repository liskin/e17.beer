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
		const col = 2 + (day - 1 + 7) % 7; /* venue is first column, Monday is second, Sunday is last */
		document.querySelector(`th.day:nth-child(${col})`).scrollIntoView({ behavior: 'smooth', inline: 'end' });
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
			reject(new Error("Geolocation is not supported by your browser"));
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

/* sort venues - compareFn takes a pair of <tr> elements and return one of -1, 0, 1 */
function sortVenuesBy(compareFn) {
	const tbody = document.querySelector('table#opening-hours > tbody');
	[...tbody.children].sort(compareFn).reduceRight((acc, x) => tbody.insertBefore(x, acc));
}

function sortVenuesByName() {
	const collator = new Intl.Collator("en");
	const getText = (tr) => tr.querySelector('th.venue').innerText;
	sortVenuesBy((a, b) => collator.compare(getText(a), getText(b)));
}

function sortVenuesByDayOpen(dayIndex) {
	const dataAttr = `day${dayIndex}-open`;
	sortVenuesBy((a, b) => {
		const aVal = parseFloat(a.dataset[dataAttr]);
		const bVal = parseFloat(b.dataset[dataAttr]);
		return aVal - bVal;
	});
}

function sortVenuesByDayClose(dayIndex) {
	const dataAttr = `day${dayIndex}-close`;
	sortVenuesBy((a, b) => {
		const aVal = parseFloat(a.dataset[dataAttr]);
		const bVal = parseFloat(b.dataset[dataAttr]);
		// Sort descending (latest closing first), but closed venues (value -1) go last
		if (bVal === -1) return -1;
		if (aVal === -1) return 1;
		return bVal - aVal;
	});
}

async function sortVenuesByDistance() {
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
	sortVenuesBy((a, b) => getVenueDistance(a) - getVenueDistance(b));
}

/* sort by distance by default if permission already granted */
async function sortVenuesByDistanceIfPermitted() {
	try {
		const p = await navigator.permissions.query({ name: "geolocation" });
		if (p.state === "granted") {
			await sortVenuesByDistance();
		}
	} catch (error) {
		console.error(error);
	}
}

document.getElementById('sort-name').addEventListener('click', (e) => { sortVenuesByName(); });
document.getElementById('sort-distance').addEventListener('click', (e) => { sortVenuesByDistance(); });

/* add event listeners for day-specific sorting buttons */
document.querySelectorAll('th.sortable').forEach((th) => {
	const dayIndex = parseInt(th.dataset.day);
	th.querySelector('.sort-open').addEventListener('click', (e) => {
		e.stopPropagation();
		sortVenuesByDayOpen(dayIndex);
	});
	th.querySelector('.sort-close').addEventListener('click', (e) => {
		e.stopPropagation();
		sortVenuesByDayClose(dayIndex);
	});
});

sortVenuesByDistanceIfPermitted();
