/**
 * API Client Configuration
 * Base URL and common fetch wrappers for communicating with the FastAPI backend.
 */

export const BASE_URL = 'http://127.0.0.1:8000/api';

interface RequestOptions extends RequestInit {
  params?: Record<string, string>;
}

export async function fetchApi<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { params, ...init } = options;
  
  let url = `${BASE_URL}${endpoint}`;
  
  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        searchParams.append(key, value);
      }
    }
    const queryString = searchParams.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  const defaultHeaders: Record<string, string> = {};
  
  // Only add Content-Type if we're sending JSON (not FormData)
  if (init.body && typeof init.body === 'string') {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  try {
    const response = await fetch(url, {
      ...init,
      headers: {
        ...defaultHeaders,
        ...init.headers,
      },
    });

    if (!response.ok) {
      let errorData;
      try {
        errorData = await response.json();
      } catch (e) {
        errorData = { detail: response.statusText };
      }
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    // Some endpoints might return empty body (e.g. DELETE)
    const text = await response.text();
    return text ? JSON.parse(text) : {} as T;
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error);
    throw error;
  }
}
