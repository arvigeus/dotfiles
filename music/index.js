const fs = require("fs").promises;
const fetch = require("node-fetch");
const chalk = require("chalk");
const prompts = require("prompts");
const playlists = require("./list");

const fileExists = async (fileName) => {
  try {
    await fs.access(fileName);
    return true;
  } catch (e) {
    return false;
  }
};

const warning = (message) =>
  console.log(
    chalk.black.bgKeyword("orange").bold(" Warning ") +
      " " +
      chalk.keyword("orange")(message)
  );
const error = (message) =>
  console.log(chalk.black.bgRed.bold(" Error ") + " " + chalk.red(message));
const info = (message) =>
  console.log(chalk.black.bgGreen.bold(" Info ") + " " + chalk.green(message));

const getSongsInfo = (songs) =>
  songs.map(({ artist, title, album }) => ({
    name: `${artist} - ${album} - ${title}`,
    shortName: `${artist} - ${title}`,
  }));

const fetchSongs = async (playlist) => {
  const { data, next } = await (await fetch(playlist)).json();
  const tracks = data.map(({ title, album, artist }) => ({
    title,
    album: album.title,
    artist: artist.name,
  }));
  return next ? [...tracks, ...(await fetchSongs(next))] : tracks;
};

const fetchPlaylist = async (sources) => {
  let songs = [];
  for (const source of sources)
    songs = [...songs, ...(await fetchSongs(source))];
  return songs.sort((a, b) => a.title.localeCompare(b.title));
};

const compareSongs = async (playlist, newSongs) => {
  let hasChanges = false;
  const shortNames = new Set();
  const longNames = new Set();
  for (const { name, shortName } of getSongsInfo(newSongs)) {
    let warned = false;
    if (longNames.has(name)) {
      error(`Likely a duplicate: \`${name}\``);
      warned = true;
      hasChanges = true;
    } else longNames.add(name);
    if (shortNames.has(shortName)) {
      if (!warned) {
        warning(`Possible duplicate: \`${shortName}\``);
        hasChanges = true;
      }
    } else shortNames.add(shortName);
  }

  const existingSongNames = new Set();
  for (const { name } of getSongsInfo(playlist)) {
    if (!longNames.has(name)) {
      longNames.add(name);
      error(`Missing song: \`${name}\``);
      hasChanges = true;
    }
    existingSongNames.add(name);
  }

  for (const name of longNames)
    if (!existingSongNames.has(name)) {
      info(`New song: \`${name}\``);
      hasChanges = true;
    }

  return hasChanges;
};

(async function () {
  for (const [playlist, sources] of Object.entries(playlists)) {
    const songs = await fetchPlaylist(sources);
    const fileName = `./playlists/${playlist}.json`;
    const existing = (await fileExists(fileName))
      ? JSON.parse(await fs.readFile(fileName, "utf-8"))
      : [];
    if (compareSongs(existing, songs)) {
      const { save } = await prompts({
        type: "confirm",
        name: "save",
        message: "Do you want to save?",
        initial: true,
      });
      if (save) await fs.writeFile(fileName, JSON.stringify(songs, null, "  "));
    } else console.info(`${playlist}: No changes`);
  }
})();
