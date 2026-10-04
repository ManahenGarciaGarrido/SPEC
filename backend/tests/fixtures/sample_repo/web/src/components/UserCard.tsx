import React from "react";

type Props = { name: string; email: string; onLogout: () => void };

/** Shows the signed-in user with a logout button. */
export function UserCard({ name, email, onLogout }: Props) {
  return (
    <div className="user-card">
      <strong>{name}</strong>
      <span>{email}</span>
      <button onClick={onLogout}>Cerrar sesión</button>
    </div>
  );
}
