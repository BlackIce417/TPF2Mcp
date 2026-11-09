import {getJson} from '../../shared/http.js';
export const getJunctions = () => getJson('/api/junctions');
export const getJunction = id => getJson(`/api/junctions/${encodeURIComponent(id)}`);
