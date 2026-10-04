import { Router, Request, Response } from "express";
import { db } from "../db";

export interface UserRow {
  id: string;
  email: string;
  displayName: string;
}

export const usersRouter = Router();

/** Returns one user by id, or 404 when it does not exist. */
export async function getUserById(req: Request, res: Response): Promise<void> {
  const row = await db.oneOrNone<UserRow>("SELECT * FROM users WHERE id = $1", [req.params.id]);
  if (!row) {
    res.status(404).json({ error: "user not found" });
    return;
  }
  res.json(row);
}

usersRouter.get("/users/:id", getUserById);
