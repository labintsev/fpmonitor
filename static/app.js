const dateInput = document.getElementById("date");
const hourSelect = document.getElementById("hour");

const playsTextarea = document.getElementById("plays");

const countElement = document.getElementById("count");
const resultInfo = document.getElementById("resultInfo");

const loadingElement = document.getElementById("loading");
const errorElement = document.getElementById("error");


function setToday() {

    const today = new Date();

    const year = today.getFullYear();

    const month = String(
        today.getMonth() + 1
    ).padStart(2, "0");

    const day = String(
        today.getDate()
    ).padStart(2, "0");

    dateInput.value =
        `${year}-${month}-${day}`;
}


function clearResult() {

    playsTextarea.value = "";

    countElement.textContent = "0";

    resultInfo.textContent =
        "Выберите дату и час";

    errorElement.classList.add("hidden");
}


async function loadPlays() {

    const date = dateInput.value;

    const hour = hourSelect.value;


    if (!date || hour === "") {

        clearResult();

        return;
    }


    loadingElement.classList.remove("hidden");

    errorElement.classList.add("hidden");


    try {

        const url =
            `/api/plays?date=${encodeURIComponent(date)}&hour=${encodeURIComponent(hour)}`;


        const response =
            await fetch(url);


        if (!response.ok) {
            throw new Error(
                "Ошибка сервера"
            );
        }


        const data =
            await response.json();


        if (!data.success) {

            throw new Error(
                data.error || "Неизвестная ошибка"
            );
        }


        /*
         * Формируем содержимое textarea.
         *
         * Например:
         *
         * 14:02:15    Coca-Cola Summer
         * 14:07:43    McDonald's Breakfast
         * 14:12:08    BMW X5
         */

        const text =
            data.plays
                .map(play => {
                    return `${play.time}    ${play.title}`;
                })
                .join("\n");


        playsTextarea.value = text;


        countElement.textContent =
            data.count;


        resultInfo.textContent =
            `${data.date} · ${String(data.hour).padStart(2, "0")}:00–${String(data.hour).padStart(2, "0")}:59`;


    } catch (error) {

        console.error(error);

        playsTextarea.value = "";

        countElement.textContent = "0";

        errorElement.textContent =
            error.message || "Ошибка загрузки данных";

        errorElement.classList.remove("hidden");

    } finally {

        loadingElement.classList.add("hidden");
    }
}


dateInput.addEventListener(
    "change",
    loadPlays
);


hourSelect.addEventListener(
    "change",
    loadPlays
);


setToday();
